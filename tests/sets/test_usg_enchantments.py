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

# --- W1G5: the cards that reported supported and did nothing ---
import dataclasses

import pytest

from engine import Game, PlayerState
from engine.auras import PUT_ONTO_BATTLEFIELD_BY
from engine.models import Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle
from tests.helpers import _damage_dealt, _mk_creature_card, resolve_stack


def _g5_game(*, interactive=()):
    """Two seats, no mana enforcement, and whichever of them answers prompts.

    A ``_g5_`` prefix and a body ending on ``return game, p1, p2`` rather than on
    the bare ``return game`` every other wave helper ends on, per SET_PLAYBOOK.md's
    note about a union splicing one helper's body onto another's signature.
    """
    p1, p2 = PlayerState(name="G5A"), PlayerState(name="G5B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _g5_put(game, seat, card):
    """One permanent onto *seat*'s battlefield, through the entry path."""
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def _g5_colored(name, power, toughness, colors):
    return dataclasses.replace(
        _mk_creature_card(name, power, toughness), colors=colors
    )


def test_w1g5_war_dance_pumps_by_the_verse_counters_it_was_sacrificed_with(set_pool):
    """Sacrifice this enchantment: Target creature gets +X/+X until end of turn,
    where X is the number of verse counters on this enchantment.

    The counters are read after the cost has already eaten the enchantment
    (CR 601.2h before CR 608.2), so this is CR 608.2h's last known information —
    and it works because the counters live on the permanent object, which the
    resolution still holds.
    """
    game, p1, _p2 = _g5_game()
    dance = _g5_put(game, 0, set_pool("USG")["War Dance"])
    bear = _g5_put(game, 0, _mk_creature_card("G5 Bear", 2, 2))
    add_counters(dance, "verse", 3)

    result = game.activate_permanent_ability(
        0, "War Dance", target_permanent_ids=[bear.permanent_id]
    )
    assert result.supported
    resolve_stack(game)

    assert dance not in p1.battlefield, "the cost sacrificed it"
    assert (bear.effective_power, bear.effective_toughness) == (5, 5)


def test_w1g5_war_dance_with_no_counters_pumps_by_nothing(set_pool):
    """The same read, at zero: a card whose X counted nothing must not fall back
    to the cast's X, which for an ability is None."""
    game, _p1, _p2 = _g5_game()
    _g5_put(game, 0, set_pool("USG")["War Dance"])
    bear = _g5_put(game, 0, _mk_creature_card("G5 Bear", 2, 2))

    game.activate_permanent_ability(
        0, "War Dance", target_permanent_ids=[bear.permanent_id]
    )
    resolve_stack(game)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


@pytest.mark.parametrize(
    "counters,targets,expected",
    [
        (1, 1, ["G5 W0"]),
        (2, 2, ["G5 W0", "G5 W1"]),
        (3, 3, ["G5 W0", "G5 W1", "G5 W2"]),
    ],
)
def test_w1g5_vile_requiem_destroys_exactly_its_verse_counters(
    set_pool, counters, targets, expected
):
    """{1}{B}, Sacrifice this enchantment: Destroy up to X target nonblack
    creatures, where X is the number of verse counters on this enchantment."""
    game, _p1, p2 = _g5_game()
    requiem = _g5_put(game, 0, set_pool("USG")["Vile Requiem"])
    victims = [
        _g5_put(game, 1, _g5_colored("G5 W%d" % i, 1, 1, ("W",))) for i in range(3)
    ]
    add_counters(requiem, "verse", counters)

    assert game.activate_permanent_ability(
        0, "Vile Requiem",
        target_permanent_ids=[v.permanent_id for v in victims[:targets]],
    ).supported
    resolve_stack(game)
    assert [card.name for card in p2.graveyard] == expected


def test_w1g5_vile_requiem_refuses_more_targets_than_it_has_counters(set_pool):
    """CR 601.2c, and the whole reason this test exists: "up to X" is a printed
    ceiling, and an unenforced ceiling is an ability that works more often than
    the card allows — silently, and in the player's favour.

    Nothing is paid: the enchantment is still on the battlefield afterwards.
    """
    game, p1, p2 = _g5_game()
    requiem = _g5_put(game, 0, set_pool("USG")["Vile Requiem"])
    victims = [
        _g5_put(game, 1, _g5_colored("G5 W%d" % i, 1, 1, ("W",))) for i in range(3)
    ]
    add_counters(requiem, "verse", 1)

    result = game.activate_permanent_ability(
        0, "Vile Requiem",
        target_permanent_ids=[v.permanent_id for v in victims],
    )
    assert not result.supported
    assert p2.graveyard == []
    assert requiem in p1.battlefield, "an illegal announcement pays nothing"


def test_w1g5_vile_requiem_beats_a_regeneration_shield(set_pool):
    """"They can't be regenerated." — the rider the where-clause used to hide."""
    game, _p1, p2 = _g5_game()
    requiem = _g5_put(game, 0, set_pool("USG")["Vile Requiem"])
    victim = _g5_put(game, 1, _g5_colored("G5 W0", 1, 1, ("W",)))
    victim.regeneration_shield = 1
    add_counters(requiem, "verse", 1)

    game.activate_permanent_ability(
        0, "Vile Requiem", target_permanent_ids=[victim.permanent_id]
    )
    resolve_stack(game)
    assert [card.name for card in p2.graveyard] == ["G5 W0"]


def test_w1g5_recantation_returns_every_permanent_it_named(set_pool):
    """{U}, Sacrifice this enchantment: Return up to X target permanents to
    their owners' hands.

    A **permanent**, not a creature: the several-target resolver defaults to
    creatures, so the land named as one of the three was dropped before the
    handler could see it.
    """
    game, _p1, p2 = _g5_game()
    recantation = _g5_put(game, 0, set_pool("USG")["Recantation"])
    bear = _g5_put(game, 1, _mk_creature_card("G5 Bear", 2, 2))
    land = _g5_put(game, 1, set_pool("USG")["Gaea's Cradle"])
    ogre = _g5_put(game, 1, _mk_creature_card("G5 Ogre", 3, 3))
    add_counters(recantation, "verse", 3)

    assert game.activate_permanent_ability(
        0, "Recantation",
        target_permanent_ids=[
            bear.permanent_id, land.permanent_id, ogre.permanent_id
        ],
    ).supported
    resolve_stack(game)

    assert p2.battlefield == []
    assert sorted(card.name for card in p2.hand) == [
        "G5 Bear", "G5 Ogre", "Gaea's Cradle",
    ]


def test_w1g5_discordant_dirge_discards_its_verse_counters_worth(set_pool):
    """{B}, Sacrifice this enchantment: Look at target opponent's hand and
    choose up to X cards from it. That player discards those cards."""
    game, _p1, p2 = _g5_game()
    dirge = _g5_put(game, 0, set_pool("USG")["Discordant Dirge"])
    for i in range(4):
        p2.hand.append(_mk_creature_card("G5 H%d" % i, 1, 1))
    add_counters(dirge, "verse", 2)

    assert game.activate_permanent_ability(
        0, "Discordant Dirge", target_player_index=1
    ).supported
    resolve_stack(game)

    for _ in range(2):
        pending = next(
            choice for choice in game.pending_choices
            if choice.kind == "revealed_hand_pick"
        )
        game.confirm_revealed_hand_pick(0, pending.data["legal_indices"][0])
    assert len(p2.graveyard) == 2
    assert len(p2.hand) == 2


def test_w1g5_discordant_dirge_may_choose_fewer_than_x(set_pool):
    """The printed "up to". Read as a plain count the chooser would be made to
    take every card the number allows, which is a different card whenever taking
    fewer is better — and the prompt chain had no way out at all."""
    game, _p1, p2 = _g5_game()
    dirge = _g5_put(game, 0, set_pool("USG")["Discordant Dirge"])
    for i in range(4):
        p2.hand.append(_mk_creature_card("G5 K%d" % i, 1, 1))
    add_counters(dirge, "verse", 3)

    game.activate_permanent_ability(0, "Discordant Dirge", target_player_index=1)
    resolve_stack(game)
    pending = next(
        choice for choice in game.pending_choices
        if choice.kind == "revealed_hand_pick"
    )
    game.confirm_revealed_hand_pick(0, pending.data["legal_indices"][0])
    assert game.confirm_revealed_hand_pick(0, None), "the ceiling permits stopping"
    assert len(p2.graveyard) == 1
    assert not game.pending_choices


def test_w1g5_a_plain_revealed_hand_pick_cannot_be_declined():
    """The other half of the same permission: Duress prints no "up to", so an
    answer naming no card is refused rather than resolving the spell for free."""
    game, _p1, p2 = _g5_game()
    p2.hand.append(_mk_creature_card("G5 Victim", 1, 1))
    game.arm_pending_choice(
        "revealed_hand_pick", 0,
        card_name="Duress", victim_index=1, legal_indices=[0], remaining=1,
        fate="discard",
    )
    assert not game.confirm_revealed_hand_pick(0, None)
    assert game.pending_choices, "the prompt is still owed"


def test_w1g5_serras_hymn_splits_its_verse_counters_among_the_targets(set_pool):
    """Sacrifice this enchantment: Prevent the next X damage that would be dealt
    this turn to any number of targets, divided as you choose.

    The pool's first activated ability with a divided target, so every step of
    CR 601.2d had to reach the activation path: the announcement, the ids it is
    stamped with, and the gate that checks the shares total X.
    """
    game, p1, _p2 = _g5_game()
    hymn = _g5_put(game, 0, set_pool("USG")["Serra's Hymn"])
    bear = _g5_put(game, 0, _mk_creature_card("G5 Bear", 4, 4))
    add_counters(hymn, "verse", 5)

    assert game.activate_permanent_ability(
        0, "Serra's Hymn",
        divided_targets=[(0, None, 3), (0, p1.battlefield.index(bear), 2)],
    ).supported
    resolve_stack(game)

    assert _damage_dealt(game, p1, 5) == 2, "3 of the 5 prevented"
    assert _damage_dealt(game, bear, 4) == 2, "2 of the 4 prevented"


def test_w1g5_serras_hymn_refuses_a_division_that_does_not_total_x(set_pool):
    """CR 601.2d, asked of an ability — and asked *before* the cost, so an
    illegal announcement leaves the enchantment on the battlefield."""
    game, p1, _p2 = _g5_game()
    hymn = _g5_put(game, 0, set_pool("USG")["Serra's Hymn"])
    bear = _g5_put(game, 0, _mk_creature_card("G5 Bear", 4, 4))
    add_counters(hymn, "verse", 4)

    result = game.activate_permanent_ability(
        0, "Serra's Hymn",
        divided_targets=[(0, None, 3), (0, p1.battlefield.index(bear), 2)],
    )
    assert not result.supported
    assert hymn in p1.battlefield
    assert p1.damage_prevention_pool == 0
    assert bear.damage_prevention_pool == 0


def test_w1g5_sporogenesis_makes_one_saproling_per_fungus_counter(set_pool):
    """Whenever a creature with a fungus counter on it dies, create a 1/1 green
    Saproling creature token for each fungus counter on that creature.

    The count is the *last known* one (CR 603.10 / 608.2h): by the time the
    trigger resolves the creature is a card in a graveyard with no counters at
    all (CR 400.7), so a live read answers zero on every board.
    """
    game, p1, _p2 = _g5_game()
    _g5_put(game, 0, set_pool("USG")["Sporogenesis"])
    victim = _g5_put(game, 0, _mk_creature_card("G5 Victim", 2, 2))
    add_counters(victim, "fungus", 3)

    victim.damage_marked = 99
    game.check_state_based_actions()
    resolve_stack(game)

    tokens = [
        permanent for permanent in p1.battlefield
        if permanent.metadata.get("is_token")
    ]
    assert len(tokens) == 3
    assert all(token.card.name == "Saproling Token" for token in tokens)


def test_w1g5_sporogenesis_ignores_a_death_with_no_fungus_counters(set_pool):
    """The trigger is narrowed by the printed noun phrase, so an ordinary death
    makes nothing — a dropped narrowing here would be a token per death."""
    game, p1, _p2 = _g5_game()
    _g5_put(game, 0, set_pool("USG")["Sporogenesis"])
    bystander = _g5_put(game, 0, _mk_creature_card("G5 Bystander", 2, 2))

    bystander.damage_marked = 99
    game.check_state_based_actions()
    resolve_stack(game)
    assert not [
        permanent for permanent in p1.battlefield
        if permanent.metadata.get("is_token")
    ]


def test_w1g5_diabolic_servitude_exiles_the_creature_it_returned(set_pool):
    """When the creature put onto the battlefield with this enchantment dies,
    exile it and return this enchantment to its owner's hand.

    Both halves. The trigger used to be classified as the *source's* own death,
    so it fired when the enchantment went to the graveyard and never when the
    creature did; and "exile it" lowered to ``exile_self``, the enchantment
    exiling itself.
    """
    game, p1, _p2 = _g5_game()
    p1.graveyard.append(_mk_creature_card("G5 Zombie", 2, 2))
    servitude = _g5_put(game, 0, set_pool("USG")["Diabolic Servitude"])
    resolve_stack(game)

    zombie = next(p for p in p1.battlefield if p.card.name == "G5 Zombie")
    assert zombie.metadata[PUT_ONTO_BATTLEFIELD_BY] == servitude.permanent_id

    zombie.damage_marked = 99
    game.check_state_based_actions()
    resolve_stack(game)

    assert [card.name for card in p1.exile] == ["G5 Zombie"]
    assert [card.name for card in p1.hand] == ["Diabolic Servitude"]
    assert p1.graveyard == []


def test_w1g5_diabolic_servitude_exiles_the_creature_when_it_leaves(set_pool):
    """When this enchantment leaves the battlefield, exile the creature put onto
    the battlefield with this enchantment. The other direction, and the one that
    names the creature while it is still a permanent."""
    game, p1, _p2 = _g5_game()
    p1.graveyard.append(_mk_creature_card("G5 Zombie", 2, 2))
    servitude = _g5_put(game, 0, set_pool("USG")["Diabolic Servitude"])
    resolve_stack(game)

    # The one leave transition, which announces CR 603.6c itself — no separate
    # fire call, and none to forget.
    game.remove_from_battlefield(servitude)
    p1.graveyard.append(servitude.card)
    resolve_stack(game)

    assert [card.name for card in p1.exile] == ["G5 Zombie"]
    assert not [p for p in p1.battlefield if p.card.name == "G5 Zombie"]


def test_w1g5_diabolic_servitude_leaves_another_enchantments_creature_alone(set_pool):
    """The record is per-permanent and by id: a second Servitude's creature is
    not this one's, and a sweep that dropped the narrowing would exile it."""
    game, p1, _p2 = _g5_game()
    p1.graveyard.append(_mk_creature_card("G5 Zombie", 2, 2))
    first = _g5_put(game, 0, set_pool("USG")["Diabolic Servitude"])
    resolve_stack(game)
    p1.graveyard.append(_mk_creature_card("G5 Ghoul", 1, 1))
    _g5_put(game, 0, set_pool("USG")["Diabolic Servitude"])
    resolve_stack(game)

    game.remove_from_battlefield(first)
    p1.graveyard.append(first.card)
    resolve_stack(game)

    assert [card.name for card in p1.exile] == ["G5 Zombie"]
    assert [p.card.name for p in p1.battlefield if p.is_creature] == ["G5 Ghoul"]


def test_w1g5_every_usg_hollow_card_now_carries_an_instruction(set_pool):
    """The guard this group exists for. Each of these compiled as *supported*
    while the named part carried no instruction at all — which is what
    ``--hollow-lines`` reports and what no ratchet test can see, because a card
    is supported when **any** of its lines is."""
    pool = set_pool("USG")
    for name in (
        "War Dance", "Vile Requiem", "Recantation", "Discordant Dirge",
        "Serra's Hymn", "Diabolic Servitude", "Sporogenesis",
        "Phyrexian Processor", "Smokestack",
    ):
        program = compile_card_oracle(pool[name])
        parts = list(program.activated_abilities) + list(program.triggered_abilities)
        hollow = [part.source_line for part in parts if part.instruction is None]
        assert not hollow, "%s still has an instruction-less part: %s" % (name, hollow)


# --- W2G3: hands, libraries, reveals and per-player effects ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.revealed_hands import hand_revealed_to

import dataclasses

from tests.helpers import _mk_card, _mk_creature_card, resolve_stack


def _g3w2_table(*, seats=2, interactive=()):
    """A table with mana enforcement off and whichever seats answer prompts.

    ``_g3w2_`` prefixed and ending on ``return game, list(game.players)`` rather
    than on a bare ``return game`` — SET_PLAYBOOK.md's note about a union
    splicing one helper's body onto another's signature.
    """
    players = [PlayerState(name=f"W2G3-{i}") for i in range(seats)]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, list(game.players)


def _g3w2_enters(game, seat, card):
    """One permanent onto *seat*'s battlefield through the one entry path."""
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def _g3w2_land(name="W2G3 Forest"):
    """A basic land card, for the halves of these sentences that turn on the
    printed type line rather than on anything a permanent computes."""
    return _mk_card(name, "Basic Land - Forest", "")


def test_w2g3_telepathy_opens_only_the_opponents_hands(set_pool):
    """"Your opponents play with their hands revealed."

    The scope is the whole card, and it is the half a widened reading would
    lose: the enchantment's own controller keeps a hidden hand. Read as
    Revelation's "players play with their hands revealed" it would be a
    symmetrical card, which is not the one printed.
    """
    card = set_pool("USG")["Telepathy"]
    assert compile_card_oracle(card).supported

    game, players = _g3w2_table(seats=3)
    _g3w2_enters(game, 0, card)

    assert hand_revealed_to(game, owner_seat=1, viewer_seat=0)
    assert hand_revealed_to(game, owner_seat=2, viewer_seat=0)
    assert not hand_revealed_to(game, owner_seat=0, viewer_seat=1), (
        "the controller's own hand stays hidden"
    )


def test_w2g3_telepathy_stops_when_it_leaves(set_pool):
    """The effect is derived from the battlefield scan, so there is nothing to
    sweep: a Telepathy that has left is simply no longer found."""
    game, players = _g3w2_table()
    telepathy = _g3w2_enters(game, 0, set_pool("USG")["Telepathy"])
    assert hand_revealed_to(game, 1, 0)

    game.remove_from_battlefield(telepathy)
    assert not hand_revealed_to(game, 1, 0)


def test_w2g3_bereavement_makes_the_dead_creatures_controller_discard(set_pool):
    """"Whenever a green creature dies, its controller discards a card."

    "Its controller" is the seat that controlled the creature, which is neither
    the enchantment's controller nor anybody targeted — and by the time the
    trigger resolves the creature is a card in a graveyard, which CR 108.4 gives
    no controller at all. So the seat has to be the one the fire site froze.
    """
    card = set_pool("USG")["Bereavement"]
    assert compile_card_oracle(card).supported

    game, players = _g3w2_table()
    _g3w2_enters(game, 0, card)
    green = _g3w2_enters(
        game, 1, dataclasses.replace(_mk_creature_card("W2G3 Elf", 1, 1), colors=("G",))
    )
    players[1].hand = [_g3w2_land(), _g3w2_land("W2G3 Plains")]

    game._permanent_to_graveyard(players[1], green)
    resolve_stack(game)
    # The trigger resolved and left a discard owed with an empty stack, so it is
    # answered here rather than by `resolve_stack` — that helper drains only
    # what *blocks* the stack, deliberately.
    assert [c.player_index for c in game.pending_choices] == [1], (
        "the discard is owed by the dead creature's controller, not by the "
        "enchantment's"
    )
    game.auto_resolve_pending_choices()

    assert len(players[1].hand) == 1, "the dead creature's controller discarded"
    assert len(players[1].graveyard) == 2, "the creature and the discarded card"
    assert players[0].hand == [], "and the enchantment's controller did not"


def test_w2g3_bereavement_ignores_a_nongreen_death(set_pool):
    """The printed narrowing, which a fire site that announced every death
    would drop — and a discard that happens more often than the card says is
    silent and in nobody's favour."""
    game, players = _g3w2_table()
    _g3w2_enters(game, 0, set_pool("USG")["Bereavement"])
    white = _g3w2_enters(
        game, 1, dataclasses.replace(_mk_creature_card("W2G3 Cleric", 1, 1), colors=("W",))
    )
    players[1].hand = [_g3w2_land()]

    game._permanent_to_graveyard(players[1], white)
    resolve_stack(game)

    assert game.pending_choices == [], "no discard was owed at all"
    assert len(players[1].hand) == 1, "a white creature dying discards nothing"


def test_w2g3_angelic_chorus_gains_the_entering_creatures_toughness(set_pool):
    """"Whenever a creature you control enters, you gain life equal to its
    toughness."

    The toughness is the *event's* number, frozen by the entry transition — read
    at resolution it would be a card in whatever state the board had left it,
    and read as the power beside it (the only characteristic the entry used to
    freeze) it would be wrong on every creature whose P and T differ. So the
    creature here is deliberately 1/4.
    """
    card = set_pool("USG")["Angelic Chorus"]
    assert compile_card_oracle(card).supported

    game, players = _g3w2_table()
    _g3w2_enters(game, 0, card)
    before = players[0].life

    _g3w2_enters(game, 0, _mk_creature_card("W2G3 Wall", 1, 4))
    resolve_stack(game)

    assert players[0].life == before + 4, "the toughness, not the power"


def test_w2g3_angelic_chorus_ignores_an_opponents_creature(set_pool):
    """"a creature **you control**" — the narrowing the trigger's own subject
    carries, which is the whole of what keeps this from being a symmetrical
    card."""
    game, players = _g3w2_table()
    _g3w2_enters(game, 0, set_pool("USG")["Angelic Chorus"])
    before = players[0].life

    _g3w2_enters(game, 1, _mk_creature_card("W2G3 Bear", 2, 2))
    resolve_stack(game)

    assert players[0].life == before


def test_w2g3_abundance_reveals_until_a_nonland_card(set_pool):
    """"If you would draw a card, you may instead choose land or nonland and
    reveal cards from the top of your library until you reveal a card of the
    chosen kind. Put that card into your hand and put all other cards revealed
    this way on the bottom of your library in any order."

    A CR 614 replacement, so the draw never happens: the card arrives in the
    hand by being *put* there (CR 121.1 — a draw is the top card of a library,
    and this is not it). The non-interactive seat takes the recorded default,
    which is "nonland".
    """
    card = set_pool("USG")["Abundance"]
    assert compile_card_oracle(card).supported

    game, players = _g3w2_table()
    _g3w2_enters(game, 0, card)
    spell = _mk_creature_card("W2G3 Spell", 2, 2)
    players[0].library = [_g3w2_land("L1"), _g3w2_land("L2"), spell, _g3w2_land("L3")]

    drawn = game._draw_with_replacements(players[0], 1)

    assert drawn == 0, "the draw was replaced, so nothing was drawn"
    assert [c.name for c in players[0].hand] == ["W2G3 Spell"]
    assert [c.name for c in players[0].library] == ["L3", "L1", "L2"], (
        "the two lands revealed on the way went to the bottom, in order"
    )


def test_w2g3_abundance_reveals_until_a_land_when_that_is_the_answer(set_pool):
    """The other kind, answered explicitly so the option index is not something
    only the default exercises."""
    game, players = _g3w2_table(interactive=(0,))
    _g3w2_enters(game, 0, set_pool("USG")["Abundance"])
    spell = _mk_creature_card("W2G3 Spell", 2, 2)
    players[0].library = [spell, _g3w2_land("L1"), _g3w2_land("L2")]

    assert game._draw_with_replacements(players[0], 1) == 0
    assert game.pending_reveal_until_kind_draws, "the interactive seat was asked"

    assert game.confirm_reveal_until_kind_draw(0, 1)  # "Land"

    assert [c.name for c in players[0].hand] == ["L1"]
    assert [c.name for c in players[0].library] == ["L2", "W2G3 Spell"]


def test_w2g3_abundance_can_be_declined_and_the_draw_still_happens(set_pool):
    """"You **may** instead" — declining leaves the event to whatever is behind
    it, which with nothing else armed is an ordinary draw. The decline is what a
    replacement offering three options is for; modelled as a no-op it would make
    the enchantment mandatory."""
    game, players = _g3w2_table(interactive=(0,))
    _g3w2_enters(game, 0, set_pool("USG")["Abundance"])
    top = _mk_creature_card("W2G3 Top", 1, 1)
    players[0].library = [top, _g3w2_land("L1")]

    assert game._draw_with_replacements(players[0], 1) == 0
    assert game.confirm_reveal_until_kind_draw(0, 2)  # "Draw a card"

    assert [c.name for c in players[0].hand] == ["W2G3 Top"], "the top card, drawn"
    assert [c.name for c in players[0].library] == ["L1"]


def test_w2g3_abundance_finds_nothing_and_puts_the_library_back(set_pool):
    """A library with no card of the chosen kind is revealed entirely and every
    card goes back to the bottom: the sentence names a card to put into a hand
    and there is none, so nothing is put anywhere and no card is drawn."""
    game, players = _g3w2_table()
    _g3w2_enters(game, 0, set_pool("USG")["Abundance"])
    players[0].library = [_g3w2_land("L1"), _g3w2_land("L2")]

    assert game._draw_with_replacements(players[0], 1) == 0
    assert players[0].hand == []
    assert [c.name for c in players[0].library] == ["L1", "L2"]


def test_w2g3_abundance_only_replaces_its_own_controllers_draws(set_pool):
    """"If **you** would draw a card" is CR 109.5's seat. An opponent's draw
    goes through untouched, which is the difference between this card and a
    symmetrical one."""
    game, players = _g3w2_table()
    _g3w2_enters(game, 0, set_pool("USG")["Abundance"])
    players[1].library = [_g3w2_land("L1"), _g3w2_land("L2")]

    assert game._draw_with_replacements(players[1], 1) == 1
    assert [c.name for c in players[1].hand] == ["L1"]


# --- W2G4: board-wide prohibitions, and who assigns combat damage ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack as _g4c_resolve


def _g4c_board(*, mine=(), theirs=(), hand0=(), life=20):
    """Two seats, mana costs off, seat 0 active. Returns ``(game, s0, s1)`` and
    ends on that tuple so no union can splice another helper onto it."""
    g4c_seat0 = PlayerState(
        name="G4-E1", battlefield=[Permanent(card=c) for c in mine],
        hand=list(hand0), life=life,
    )
    g4c_seat1 = PlayerState(
        name="G4-E2", battlefield=[Permanent(card=c) for c in theirs], life=life,
    )
    g4c_game = Game(players=[g4c_seat0, g4c_seat1])
    g4c_game.enforce_mana_costs = False
    g4c_game.active_player_index = 0
    g4c_game._sync_control()
    return g4c_game, g4c_seat0, g4c_seat1


def _g4c_creature(name, power=2, toughness=2):
    from tests.helpers import _mk_creature_card

    return _mk_creature_card(name, power, toughness)


def test_w2g4_bedlam_stops_every_block_including_its_controllers(set_pool):
    """"Creatures can't block" names nobody, so it binds the enchantment's own
    controller too (CR 109.5 has nothing to narrow). The enforcement site has
    scanned for this kind since Katabatic Winds; nothing had ever printed the
    blocking half on its own, so the row that produces it was the missing half."""
    pool = set_pool("USG")
    game, mine, theirs = _g4c_board(
        mine=[pool["Bedlam"], _g4c_creature("G4C Mine")],
        theirs=[_g4c_creature("G4C Theirs")],
    )
    my_creature = mine.battlefield[1]
    their_creature = theirs.battlefield[0]

    assert not game._can_block_attacker(their_creature, my_creature)
    assert not game._can_block_attacker(my_creature, their_creature)
    # …and attacking is untouched: this is the blocking half alone.
    assert game.can_attack(my_creature, 1)


def test_w2g4_arcane_laboratory_caps_each_seat_separately(set_pool):
    """CR 601.3a restricts the player who is *casting*, so the tally is that
    seat's own. One shared count would let an opponent's first spell spend
    everybody's allowance."""
    pool = set_pool("USG")
    shock = set_pool("M21")["Shock"]
    game, mine, theirs = _g4c_board(mine=[pool["Arcane Laboratory"]])
    mine.hand.extend([shock, shock])
    theirs.hand.extend([shock, shock])

    assert game.cast_from_hand(0, "Shock", target_player_index=1).supported
    refused = game.cast_from_hand(0, "Shock", target_player_index=1)
    assert not refused.supported and "Arcane Laboratory" in refused.details
    # The opponent has cast nothing yet, so their first is still legal — and the
    # enchantment binds them too, so their second is not.
    assert game.cast_from_hand(1, "Shock", target_player_index=0).supported
    assert not game.cast_from_hand(1, "Shock", target_player_index=0).supported


def test_w2g4_the_cap_is_claimed_by_the_reader_that_enforces_it(set_pool):
    """A restriction claimed and not enforced is an enchantment that reports
    supported while everybody keeps casting, so the claim and the gate ask one
    function — and the number is payload, not part of the rule."""
    from engine.cast_restrictions import spell_cap_line

    card = set_pool("USG")["Arcane Laboratory"]
    assert compile_card_oracle(card).supported
    assert spell_cap_line(card.oracle_text) == 1
    assert spell_cap_line("Each player can't cast more than three spells each turn.") == 3
    assert spell_cap_line("Each player can't cast more than a spell each turn.") is None
    assert spell_cap_line("Creature spells can't be cast.") is None


def test_w2g4_defensive_formation_moves_the_assignment_to_the_defender(set_pool):
    """CR 510.1a names the *attacking* player as the one who divides a blocked
    creature's damage; this substitutes the defending player, which is the same
    substitution CR 702.22j makes for a band — so it is answered at the same
    seam, and what the prompt offers and what the damage step honours cannot
    disagree."""
    pool = set_pool("USG")
    game, mine, theirs = _g4c_board(
        mine=[_g4c_creature("G4C Attacker", 2, 2)],
        theirs=[pool["Defensive Formation"],
                _g4c_creature("G4C Wall A", 0, 8),
                _g4c_creature("G4C Wall B", 0, 8)],
    )
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    assert game.declare_attackers(0, {0: 1})[0]
    game.current_step = "declare_blockers"
    assert game.declare_blockers(1, {1: 0, 2: 0})[0]

    assert game._defender_assigns_attacker_damage(0)
    assert game.assign_banding_combat_damage(1, {0: {1: 2, 2: 0}})[0]
    game.current_step = "combat_damage"
    game.resolve_all_combat_damage(0)

    wall_a, wall_b = theirs.battlefield[1], theirs.battlefield[2]
    assert (wall_a.damage_marked, wall_b.damage_marked) == (2, 0)


def test_w2g4_the_substitution_is_the_defenders_own_and_not_an_opponents(set_pool):
    """"You" is CR 109.5's seat: an opponent's copy of the card moves nobody
    else's assignment, and a reader that scanned every battlefield would hand
    the division to whoever happened to own one."""
    from engine.combat_assignment import defender_assigns_all_damage

    pool = set_pool("USG")
    game, mine, theirs = _g4c_board(
        mine=[pool["Defensive Formation"], _g4c_creature("G4C Attacker")],
        theirs=[_g4c_creature("G4C Blocker A", 0, 8),
                _g4c_creature("G4C Blocker B", 0, 8)],
    )
    assert defender_assigns_all_damage(game, 0)
    assert not defender_assigns_all_damage(game, 1)

    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    assert game.declare_attackers(0, {1: 1})[0]
    game.current_step = "declare_blockers"
    assert game.declare_blockers(1, {0: 1, 1: 1})[0]
    assert not game._defender_assigns_attacker_damage(1)


# --- W2G1: the static damage-modifiers, and the two seat-narrowed triggers ---
from engine import Game as _G1Game, PlayerState as _G1PlayerState  # noqa: E402
from engine.damage_events import deal_damage as _g1e_deal  # noqa: E402
from engine.models import Permanent as _G1ePermanent  # noqa: E402
from engine.oracle import compile_card_oracle as _g1e_compile  # noqa: E402
from engine.game_types import OracleExecutionContext as _G1eContext  # noqa: E402

from tests.helpers import resolve_stack as _g1e_resolve  # noqa: E402


def _g1e_board(pool, mine=(), theirs=(), life=(20, 20), hands=(0, 0)):
    """Two seats with sized hands. Ends on the control sync, which is this
    block's own helper tail."""
    game = _G1Game(players=[
        _G1PlayerState(name="G1eA", battlefield=list(mine), life=life[0],
                       hand=[pool["Remote Isle"]] * hands[0],
                       library=[pool["Remote Isle"]] * 8),
        _G1PlayerState(name="G1eB", battlefield=list(theirs), life=life[1],
                       hand=[pool["Remote Isle"]] * hands[1],
                       library=[pool["Remote Isle"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


def test_w2g1_worship_floors_life_only_while_a_creature_is_there(set_pool):
    """"If you control a creature, damage that would reduce your life total to
    less than 1 reduces it to 1 instead."

    Ali from Cairo's sentence with CR 611.2's condition in front of it, and the
    condition is the whole test: the old reader was a *substring* test over the
    controller's permanents, and Worship's line contains Ali from Cairo's
    constant whole — so a Worship on an empty board would have floored the life
    total of a player who controls nothing.

    Both numbers are asserted, because the effect is CR 120.4c: the damage is
    *dealt* in full and only its result is capped, which is what lifelink and
    every "deals damage" trigger read.
    """
    pool = set_pool("USG")
    worship = _G1ePermanent(card=pool["Worship"])
    game = _g1e_board(pool, mine=[worship], life=(5, 20))
    bare = _g1e_deal(game, {"recipient": game.players[0], "amount": 9, "source": None})
    assert (bare.dealt, bare.result) == (9, 9), "no creature, no floor"

    worship = _G1ePermanent(card=pool["Worship"])
    creature = _G1ePermanent(card=pool["Coral Merfolk"])
    game = _g1e_board(pool, mine=[worship, creature], life=(5, 20))
    held = _g1e_deal(game, {"recipient": game.players[0], "amount": 9, "source": None})
    assert held.dealt == 9, "CR 120.4b: the damage is dealt in full"
    assert held.result == 4, "CR 120.4c: only the life lost is capped, at 1 life"


def test_w2g1_sulfuric_vapors_adds_a_point_to_a_red_spell(set_pool):
    """"If a red spell would deal damage to a permanent or player, it deals that
    much damage plus 1 to that permanent or player instead."

    Benevolent Unicorn's sentence one word apart, so the two are one signed
    delta rather than twins. Two claims are tested: the addition, and the colour
    — a green spell's damage is untouched, which is what keeps the narrowing from
    being read and dropped.
    """
    pool = set_pool("USG")
    vapors = _G1ePermanent(card=pool["Sulfuric Vapors"])
    game = _g1e_board(pool, mine=[vapors])
    game.players[0].hand.append(pool["Heat Ray"])
    target = _G1ePermanent(card=pool["Blanchwood Treefolk"])
    game._put_permanent_onto_battlefield(1, target, None)
    game._sync_control()

    assert game.cast_from_hand(
        0, "Heat Ray", target_permanent_ids=[target.permanent_id], x_value=2
    ).supported
    _g1e_resolve(game)
    assert target.damage_marked == 3, "a red spell's 2 becomes 3"


def test_w2g1_the_damage_delta_reads_both_printed_directions():
    """The matcher's own test, which the board cannot give: the sign is the
    printed word, and the two halves of the sentence must name the **same**
    recipients — a card reducing damage to a permanent and dealing the reduced
    amount to a creature is not this effect and stays unclaimed."""
    from engine.replacements import source_damage_delta

    assert source_damage_delta(
        "If a spell would deal damage to a permanent or player, it deals that "
        "much damage minus 1 to that permanent or player instead."
    ) == ("spell", -1)
    assert source_damage_delta(
        "If a red spell would deal damage to a permanent or player, it deals "
        "that much damage plus 1 to that permanent or player instead."
    ) == ("red spell", 1)
    assert source_damage_delta(
        "If a spell would deal damage to a permanent or player, it deals that "
        "much damage plus 1 to that creature or player instead."
    ) is None


def test_w2g1_energy_field_shields_only_foreign_sources(set_pool):
    """"Prevent all damage that would be dealt to you by sources you don't
    control."

    Glacial Chasm's blanket with a *relation* on it rather than a class of
    object: CR 109.5 gives a source a controller, and the clause compares that
    seat with the protected one. Dropped, the Field would shield its controller
    from their own Flesh Reaver.
    """
    pool = set_pool("USG")
    field = _G1ePermanent(card=pool["Energy Field"])
    mine = _G1ePermanent(card=pool["Coral Merfolk"])
    theirs = _G1ePermanent(card=pool["Coral Merfolk"])
    game = _g1e_board(pool, mine=[field, mine], theirs=[theirs])

    foreign = _g1e_deal(game, {"recipient": game.players[0], "amount": 3, "source": theirs})
    own = _g1e_deal(game, {"recipient": game.players[0], "amount": 3, "source": mine})
    assert foreign.dealt == 0, "a source they don't control is prevented"
    assert own.dealt == 3, "their own source is not"


def test_w2g1_energy_field_breaks_on_a_card_reaching_its_own_graveyard(set_pool):
    """"When a card is put into your graveyard from anywhere, sacrifice this
    enchantment."

    The card reported *supported* the moment its prevention line was claimed,
    with this trigger doing nothing at all — a card is supported when any of its
    lines is. "Your" is the watching permanent's controller and never the card's
    owner, so an opponent's own mill must not break it.
    """
    pool = set_pool("USG")
    field = _G1ePermanent(card=pool["Energy Field"])
    game = _g1e_board(pool, mine=[field])

    game.put_card_into_graveyard(game.players[1], pool["Remote Isle"])
    _g1e_resolve(game)
    assert game.is_on_battlefield(field), "an opponent's graveyard is not yours"

    game.put_card_into_graveyard(game.players[0], pool["Remote Isle"])
    _g1e_resolve(game)
    assert not game.is_on_battlefield(field), "a card reaching your graveyard breaks it"


def test_w2g1_bulwark_deals_the_difference_between_two_hands(set_pool):
    """"…deals X damage to target opponent, where X is the number of cards in
    your hand minus the number of cards in that player's hand."

    The first printed difference of two *counts*. Clamped at zero (CR 107.1b):
    a smaller hand deals no damage rather than healing the opponent, and CR 120.8
    makes a source that would deal 0 deal none at all.
    """
    pool = set_pool("USG")
    for mine, theirs, expected in ((5, 2, 3), (2, 5, 0), (3, 3, 0)):
        bulwark = _G1ePermanent(card=pool["Bulwark"])
        game = _g1e_board(pool, mine=[bulwark], hands=(mine, theirs))
        trig = _g1e_compile(bulwark.card).triggered_abilities[0]
        game._execute_oracle_instruction(trig.instruction, _G1eContext(
            card=bulwark.card, caster=game.players[0], target=game.players[1],
            source_permanent=bulwark,
        ))
        assert game.players[1].life == 20 - expected, (mine, theirs, game.log)


def test_w2g1_antagonism_spares_a_player_whose_opponent_was_hurt(set_pool):
    """"…deals 2 damage to that player unless one of their opponents was dealt
    damage this turn."

    The first "unless" in the pool that is a *fact* rather than a price, and the
    first condition read off the turn's damage ledger for a seat. Never a life
    total: a life total is the turn's net, so a player dealt 4 who gained 4 has
    been dealt damage and lost no life.

    The third case is the one that makes the clause narrow rather than merely
    present: damage dealt to the *end-step player themselves* is not damage to
    one of their opponents, so the enchantment still fires.
    """
    pool = set_pool("USG")

    def _run(hurt_seat, subject_seat):
        antagonism = _G1ePermanent(card=pool["Antagonism"])
        game = _g1e_board(pool, mine=[antagonism])
        if hurt_seat is not None:
            game._deal_damage_to_player(game.players[hurt_seat], 1, source=antagonism)
        trig = _g1e_compile(antagonism.card).triggered_abilities[0]
        game._execute_oracle_instruction(trig.instruction, _G1eContext(
            card=antagonism.card, caster=game.players[0],
            target=game.players[subject_seat], source_permanent=antagonism,
            trigger_context={"event_subject_player": subject_seat},
        ))
        return [p.life for p in game.players]

    assert _run(None, 0) == [18, 20], "nobody hurt: the end-step player takes 2"
    assert _run(1, 0) == [20, 19], "their opponent was hurt: no damage"
    assert _run(0, 0) == [17, 20], (
        "the player's own damage is not one of their opponents'"
    )


# --- W2G5: Greater Good and Lurking Evil — costs that read a board ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g5e_slot(game, seat, permanent):
    """*permanent*'s slot in *seat*'s battlefield, for ``cost_permanent_index``."""
    for index, found in enumerate(game.controlled_by(seat)):
        if found is permanent:
            return index
    raise AssertionError("permanent is not on that battlefield")


def _g5e_game(set_pool, *names, seat=0):
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    pool = set_pool("USG")
    made = []
    for name in names:
        perm = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(seat, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        made.append(perm)
    return game, made


def test_greater_good_draws_the_sacrificed_creatures_power_then_discards_three(
    set_pool, catalog_by_name
):
    """"Sacrifice a creature: Draw cards equal to the sacrificed creature's
    power, then discard three cards."

    Both halves, because the discard is the half a sentence read as one
    instruction would lose — and the draw is a characteristic of what the cost
    ate (CR 601.2h), so it is read off the record the payment kept rather than
    off a board that no longer holds it.
    """
    game, (good,) = _g5e_game(set_pool, "Greater Good")
    alice = game.players[0]
    alice.library = [catalog_by_name["Forest"]] * 12
    alice.hand = [catalog_by_name["Mountain"]] * 4
    ogre = Permanent(card=catalog_by_name["Hill Giant"])
    game._put_permanent_onto_battlefield(0, ogre, None)

    game.activate_permanent_ability(
        0, "Greater Good", cost_permanent_index=_g5e_slot(game, 0, ogre),
    )
    resolve_stack(game)
    # The discard is a decision its seat owes, and `resolve_stack` answers only
    # what blocks the stack — the same shape Bazaar of Baghdad's ability has
    # had since it shipped. Settling it here is what the helper's docstring
    # says to do when the prompt itself is the thing under test.
    game.auto_resolve_pending_choices()

    assert [c.name for c in alice.graveyard][0] == "Hill Giant"
    # 4 in hand + 3 drawn (Hill Giant is 3/3) - 3 discarded
    assert len(alice.hand) == 4
    assert len(alice.library) == 9


def test_greater_good_reads_the_power_the_creature_last_had(set_pool, catalog_by_name):
    """CR 608.2h's last-known information, and the reason the record carries a
    ``Permanent`` rather than a card: a +1/+1 counter is layer 7, so the number
    is the *effective* power the creature had as it left, not its printed one.
    """
    game, (good,) = _g5e_game(set_pool, "Greater Good")
    alice = game.players[0]
    alice.library = [catalog_by_name["Forest"]] * 12
    alice.hand = [catalog_by_name["Mountain"]] * 5
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    from engine.pt import add_pt_modifier

    add_pt_modifier(bears, 3, 3)

    game.activate_permanent_ability(
        0, "Greater Good", cost_permanent_index=_g5e_slot(game, 0, bears),
    )
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(alice.library) == 7, "5/5 after the boost, so five drawn"


def test_lurking_evil_pays_half_the_life_total_rounded_up(set_pool):
    """"Pay half your life, rounded up: This enchantment becomes a 4/4
    Phyrexian Horror creature with flying."

    The cost has no printed number: it is a fraction of the payer's own total,
    read when the ability is activated (CR 601.2f) and rounded as the card says
    (CR 107.2). An odd total is used so a reader rounding the other way is
    caught, and the body is asserted as well as the payment — the effect
    compiled before this group started and only the cost refused.
    """
    game, (evil,) = _g5e_game(set_pool, "Lurking Evil")
    game.players[0].life = 15

    game.activate_permanent_ability(0, "Lurking Evil")
    resolve_stack(game)

    assert game.players[0].life == 7, "15 -> pay 8 (half rounded up)"
    assert evil.is_creature
    assert evil.has_type("horror")
    assert not evil.has_type("enchantment"), "it becomes a creature instead"
    assert (evil.effective_power, evil.effective_toughness) == (4, 4)
    assert evil.has_keyword("flying")


def test_lurking_evil_costs_a_second_activation_half_of_what_is_left(set_pool):
    """The cost is recomputed each time (CR 601.2f), not frozen at the printed
    number a flat reader would have invented. Two activations at different
    totals, because one would look right at whichever number the test picked.
    """
    game, (evil,) = _g5e_game(set_pool, "Lurking Evil")
    game.players[0].life = 20

    game.activate_permanent_ability(0, "Lurking Evil")
    resolve_stack(game)
    assert game.players[0].life == 10

    game.activate_permanent_ability(0, "Lurking Evil")
    resolve_stack(game)
    assert game.players[0].life == 5


# --- W2G5: Darkest Hour and Lingering Mirage — two statics one word apart ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g5c_two_seats():
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    return game, alice, bob


def test_darkest_hour_makes_every_creature_black_on_both_sides(
    set_pool, catalog_by_name
):
    """"All creatures are black."

    CR 105.3, layer 5: the colour is **set**, not added, so a green creature is
    black and not green-and-black. Both battlefields, because the sentence
    names no controller — and a non-creature is the control, since the noun is
    payload on the row this uses and a scope read too widely would recolour the
    artifact too.
    """
    game, _alice, _bob = _g5c_two_seats()
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    mox = Permanent(card=catalog_by_name["Mox Ruby"])
    game._put_permanent_onto_battlefield(0, mox, None)
    assert bears.effective_colors == {"G"}

    game._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("USG")["Darkest Hour"]), None
    )
    game._recompute_continuous_effects()

    assert bears.effective_colors == {"B"}, "set, not added (CR 105.3)"
    assert mox.effective_colors == set(), "an artifact is not a creature"


def test_darkest_hours_colour_ends_with_the_enchantment(set_pool, catalog_by_name):
    """The contribution is derived from the source's own text on every
    recompute, so a source that has left contributes nothing — there is no
    stamped override to sweep.
    """
    game, _alice, _bob = _g5c_two_seats()
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    hour = Permanent(card=set_pool("USG")["Darkest Hour"])
    game._put_permanent_onto_battlefield(0, hour, None)
    game._recompute_continuous_effects()
    assert bears.effective_colors == {"B"}

    game.remove_from_battlefield(hour)
    game._recompute_continuous_effects()

    assert bears.effective_colors == {"G"}


def test_lingering_mirage_makes_the_land_an_island(set_pool, catalog_by_name):
    """"Enchanted land is an Island."

    Evil Presence's sentence with one word changed, and both halves of the
    engine read the word wrongly: the support gate matched "a [a-z]+" (Island
    takes "an") and the application compared against the literal "enchanted
    land is a swamp". The tap is the assertion, because a type change nothing
    reads is a card that attaches and does nothing.
    """
    game, _alice, bob = _g5c_two_seats()
    forest = Permanent(card=catalog_by_name["Forest"])
    game._put_permanent_onto_battlefield(1, forest, None)
    game.players[0].hand = [set_pool("USG")["Lingering Mirage"]]

    game.cast_from_hand(
        0, "Lingering Mirage", target_player_index=1, target_permanent_index=0,
    )
    resolve_stack(game)

    assert sorted(forest.basic_land_types) == ["island"]
    assert not forest.has_type("forest"), "CR 305.7 replaces the subtype"
    game.tap_land_for_mana(1, "Forest", permanent_id=forest.permanent_id)
    assert bob.mana_pool.get("U") == 1


# --- W2G5: Greener Pastures — a superlative across every seat ---
def _g5p_upkeep(game, seat):
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def _g5p_saprolings(game, seat):
    return sum(1 for p in game.controlled_by(seat) if "Saproling" in p.card.name)


def _g5p_board(set_pool, catalog_by_name, mine, theirs):
    """Greener Pastures on seat 0, with *mine* / *theirs* lands beside it."""
    game, _alice, _bob = _g5c_two_seats()
    game._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("USG")["Greener Pastures"]), None
    )
    for _ in range(mine):
        game._put_permanent_onto_battlefield(
            0, Permanent(card=catalog_by_name["Forest"]), None
        )
    for _ in range(theirs):
        game._put_permanent_onto_battlefield(
            1, Permanent(card=catalog_by_name["Island"]), None
        )
    return game


def test_greener_pastures_pays_whichever_seat_leads_on_lands(
    set_pool, catalog_by_name
):
    """"At the beginning of each player's upkeep, if that player controls more
    lands than each other player, the player creates a 1/1 green Saproling
    creature token."

    Two independent gaps met on this card and only one of them was the
    superlative: the *token* also went to the wrong seat, because "that player"
    read ``context.target`` — whatever the resolution was carrying — where the
    seat is the one the upkeep froze (CR 603.10).

    The enchantment is on seat 0 throughout and the *opponent* is the one that
    gets the token in the second board, which is what the wrong reading could
    not produce.
    """
    game = _g5p_board(set_pool, catalog_by_name, mine=3, theirs=1)
    for seat in (0, 1):
        _g5p_upkeep(game, seat)
    assert (_g5p_saprolings(game, 0), _g5p_saprolings(game, 1)) == (1, 0)

    game = _g5p_board(set_pool, catalog_by_name, mine=1, theirs=3)
    for seat in (0, 1):
        _g5p_upkeep(game, seat)
    assert (_g5p_saprolings(game, 0), _g5p_saprolings(game, 1)) == (0, 1)


def test_greener_pastures_is_silent_on_a_level_board(set_pool, catalog_by_name):
    """"More … than each other player" is strict, so a tie is nobody's lead.

    The control the two boards above need: a superlative read as ">=" would
    hand a token to *both* seats every turn, which is a different card.
    """
    game = _g5p_board(set_pool, catalog_by_name, mine=2, theirs=2)
    for seat in (0, 1):
        _g5p_upkeep(game, seat)

    assert (_g5p_saprolings(game, 0), _g5p_saprolings(game, 1)) == (0, 0)


# --- W2G2: Planar Void — every card that reaches a graveyard is exiled ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g2e_kill(game, seat, permanent):
    """Kill *permanent*: file its card, then take the object off the
    battlefield — the order ``_destroy_swept_permanents`` uses, and the order
    the death triggers are announced in. ``_permanent_to_graveyard`` is what
    announces them, and it is called while the permanent is still controlled,
    so a "whenever a creature **you control** dies" observer can still answer
    what it controlled. Removing first silently unfires every such trigger.
    W2G2's own.
    """
    game._permanent_to_graveyard(game.players[seat], permanent)
    game.remove_from_battlefield(permanent)
    resolve_stack(game)


def _g2e_void(set_pool, *, seat=0):
    """Seat *seat* controls Planar Void. W2G2's own enchantment-block helper."""
    alice, bob = PlayerState(name="G2E-A"), PlayerState(name="G2E-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    void = Permanent(card=set_pool("USG")["Planar Void"])
    game._put_permanent_onto_battlefield(seat, void, None)
    return game, alice, bob, void


def test_w2g2_planar_void_exiles_a_card_milled_out_of_a_library(set_pool):
    """"Whenever another card is put into a graveyard from anywhere, exile that
    card."

    A mill is the half a death-shaped reading would miss: the card was never a
    permanent, so nothing on any battlefield could have watched it leave.
    """
    game, alice, _, _ = _g2e_void(set_pool)
    filler = set_pool("USG")["Sanctum Custodian"]
    alice.library = [filler, filler]

    game.put_card_into_graveyard(alice, alice.library.pop(0), from_zone="library")
    resolve_stack(game)

    assert not alice.graveyard
    assert [c.name for c in alice.exile] == ["Sanctum Custodian"]


def test_w2g2_planar_void_reaches_the_other_seat_s_graveyard_too(set_pool):
    """"**a** graveyard", not "your graveyard" — the pile is anybody's, which
    is the narrowing Forbidden Crypt's sentence has and this one does not."""
    game, _, bob, _ = _g2e_void(set_pool)
    filler = set_pool("USG")["Sanctum Custodian"]

    game.put_card_into_graveyard(bob, filler)
    resolve_stack(game)

    assert not bob.graveyard
    assert [c.name for c in bob.exile] == ["Sanctum Custodian"]


def test_w2g2_planar_void_exiles_a_creature_that_died(set_pool):
    """The death half, through the same seam — and the Void itself stays on the
    battlefield, which is what "another card" buys."""
    game, alice, _, void = _g2e_void(set_pool)
    victim = Permanent(card=set_pool("USG")["Sanctum Custodian"])
    game._put_permanent_onto_battlefield(0, victim, None)

    _g2e_kill(game, 0, victim)

    assert not alice.graveyard
    assert [c.name for c in alice.exile] == ["Sanctum Custodian"]
    assert game.is_on_battlefield(void)


def test_w2g2_no_rest_returns_only_what_died_this_turn(set_pool):
    """"Sacrifice this enchantment: Return to your hand all creature cards in
    your graveyard that were put there from the battlefield this turn."

    Three cards in one graveyard and only one of them qualifies: the creature
    that died this turn comes back, the creature that was discarded does not
    (it never touched the battlefield), and the non-creature card does not
    either. Without the history the sweep would take the discarded one too,
    which is a card doing strictly more than it prints.
    """
    pool = set_pool("USG")
    alice, bob = PlayerState(name="G2E-A"), PlayerState(name="G2E-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    rest = Permanent(card=pool["No Rest for the Wicked"])
    game._put_permanent_onto_battlefield(0, rest, None)

    discarded = pool["Serra Zealot"]
    alice.graveyard = [discarded, pool["Gamble"]]
    died = Permanent(card=pool["Shivan Hellkite"])
    game._put_permanent_onto_battlefield(0, died, None)
    _g2e_kill(game, 0, died)

    game.activate_permanent_ability(0, "No Rest for the Wicked")
    resolve_stack(game)

    assert [c.name for c in alice.hand] == ["Shivan Hellkite"]
    assert [c.name for c in alice.graveyard] == [
        "Serra Zealot", "Gamble", "No Rest for the Wicked",
    ]


def test_w2g2_no_rest_forgets_at_the_turn_boundary(set_pool):
    """"This turn" is the window, and it is the half a bare "creature cards in
    your graveyard" reading would lose: a creature that died on the previous
    turn stays where it is."""
    pool = set_pool("USG")
    alice, bob = PlayerState(name="G2E-A"), PlayerState(name="G2E-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    rest = Permanent(card=pool["No Rest for the Wicked"])
    game._put_permanent_onto_battlefield(0, rest, None)

    died = Permanent(card=pool["Shivan Hellkite"])
    game._put_permanent_onto_battlefield(0, died, None)
    _g2e_kill(game, 0, died)
    alice.cards_put_into_your_graveyard_from_battlefield_this_turn = []

    game.activate_permanent_ability(0, "No Rest for the Wicked")
    resolve_stack(game)

    assert not alice.hand
    assert [c.name for c in alice.graveyard] == [
        "Shivan Hellkite", "No Rest for the Wicked",
    ]


def test_w2g2_no_rest_counts_copies_rather_than_matching_by_name(set_pool):
    """Two copies of one card in a deck are the same ``CardDefinition``, so
    "was it put there this turn" cannot be answered of a card by looking at it.
    One copy died and one was discarded: exactly one comes back."""
    pool = set_pool("USG")
    alice, bob = PlayerState(name="G2E-A"), PlayerState(name="G2E-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    rest = Permanent(card=pool["No Rest for the Wicked"])
    game._put_permanent_onto_battlefield(0, rest, None)

    hellkite = pool["Shivan Hellkite"]
    alice.graveyard = [hellkite]
    died = Permanent(card=hellkite)
    game._put_permanent_onto_battlefield(0, died, None)
    game._permanent_to_graveyard(alice, died)

    game.activate_permanent_ability(0, "No Rest for the Wicked")
    resolve_stack(game)

    assert [c.name for c in alice.hand] == ["Shivan Hellkite"]
    assert [c.name for c in alice.graveyard] == [
        "Shivan Hellkite", "No Rest for the Wicked",
    ]


def test_w2g2_remembrance_searches_for_the_dead_creature_s_name(set_pool):
    """"Whenever a nontoken creature you control dies, you may search your
    library for a card with the same name as that creature, reveal it, put it
    into your hand, then shuffle."

    The narrowing is the whole card: the library holds one copy of the dead
    creature and one of something else, and only the first is a legal find. A
    search that dropped "with the same name as that creature" would offer both.
    """
    from engine.search_filters import search_matches

    pool = set_pool("USG")
    alice, bob = PlayerState(name="G2E-A"), PlayerState(name="G2E-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    # The "you may" is a real offer, so the seat has to be one that can take it:
    # a non-interactive seat declines by default and the search is never armed.
    game.interactive_seats = {0}
    game._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Remembrance"]), None
    )
    zealot, hellkite = pool["Serra Zealot"], pool["Shivan Hellkite"]
    alice.library = [zealot, hellkite]
    victim = Permanent(card=zealot)
    game._put_permanent_onto_battlefield(0, victim, None)

    _g2e_kill(game, 0, victim)

    assert game.confirm_optional_pay(0, "Remembrance", accept=True)
    game._settle()

    prompt = game.pending_choice_of("search_library", 0)
    assert prompt is not None, "the may was offered and taken"
    payload = {
        "restrictions": prompt.data["restrictions"],
        "card_type": prompt.data["card_type"],
    }
    admitted = [
        c.name for c in alice.library
        if search_matches(c, payload, game=game, owner=0)
    ]
    assert admitted == ["Serra Zealot"]

    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="library"
    )
    game._settle()

    assert [c.name for c in alice.hand] == ["Serra Zealot"]


def test_w2g2_remembrance_ignores_a_token_s_death(set_pool):
    """"**nontoken**" is enforced, not decoration: a token that dies leaves no
    card to look for, and the trigger does not fire at all."""
    pool = set_pool("USG")
    alice, bob = PlayerState(name="G2E-A"), PlayerState(name="G2E-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Remembrance"]), None
    )
    alice.library = [pool["Serra Zealot"]]
    token = Permanent(card=pool["Serra Zealot"])
    token.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(0, token, None)

    _g2e_kill(game, 0, token)

    assert not game.pending_choices, "no offer at all, not an offer declined"
    assert game.pending_choice_of("search_library", 0) is None
    assert not alice.hand


def test_w2g2_planar_void_and_serra_avatar_both_watch_one_arrival(set_pool):
    """One move, two abilities: Planar Void's board-wide trigger and Serra
    Avatar's own ride the *same* announcement, which is why the seam emits one
    event rather than two — CR 603.3b puts simultaneous triggers on the stack
    together.

    Both are on the stack, the Void resolves first and exiles the card, and the
    Avatar's ability shuffles anyway: CR 701.24c says a library named by a
    shuffle is shuffled even when the object is not where it was expected.
    """
    pool = set_pool("USG")
    alice, bob = PlayerState(name="G2E-A"), PlayerState(name="G2E-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(
        1, Permanent(card=pool["Planar Void"]), None
    )
    avatar = Permanent(card=pool["Serra Avatar"])
    game._put_permanent_onto_battlefield(0, avatar, None)

    game._permanent_to_graveyard(alice, avatar)
    game.remove_from_battlefield(avatar)

    assert len(game.stack) == 2, "one move, two triggers, one batch"

    resolve_stack(game)

    assert [c.name for c in alice.exile] == ["Serra Avatar"]
    assert not alice.graveyard and not alice.library


def test_w2g2_a_replaced_arrival_fires_planar_void_at_all(set_pool):
    """CR 614: a replacement means the card never reaches the graveyard, so the
    trigger that watches arrivals has nothing to watch. Yawgmoth's Will's own
    second line is the replacement, which is what makes this pair testable at
    all — the seam that announces is the seam the replacement guards.
    """
    pool = set_pool("USG")
    alice, bob = PlayerState(name="G2E-A"), PlayerState(name="G2E-B")
    alice.hand = [pool["Yawgmoth's Will"]]
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(
        1, Permanent(card=pool["Planar Void"]), None
    )

    game.cast_from_hand(0, "Yawgmoth's Will")
    resolve_stack(game)

    game.put_card_into_graveyard(alice, pool["Gamble"])

    assert not game.stack, "nothing arrived, so nothing triggered"
    assert not alice.graveyard
    assert [c.name for c in alice.exile] == ["Yawgmoth's Will", "Gamble"]


# --- W3G2: Sneak Attack, a grant that outlives its sentence ---
#
# Three printed steps, each given a game rather than a compile check: the
# put-from-hand, an *undurated* keyword grant to the permanent that step made
# (CR 611.2a — it lasts as long as the object, not until end of turn), and a
# delayed sacrifice bound to that same permanent (CR 603.7c). The last two are
# riders on an offer, so the empty-hand direction is tested too: a rider that
# fired on an action that did not happen is the failure
# `handlers/control_flow._action_is_takeable` exists for.
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g2s_sneak_attack_board(set_pool, hand=()):
    """Seat 0 with Sneak Attack on the battlefield and *hand* in hand.

    Returns ``(game, alice, bob)`` — never a bare game, so no mechanical union
    can splice a different group's helper body onto this signature.
    """
    g2s_alice = PlayerState(name="G2S-A", hand=list(hand))
    g2s_bob = PlayerState(name="G2S-B")
    g2s_game = Game(players=[g2s_alice, g2s_bob])
    g2s_game.enforce_mana_costs = False
    g2s_game._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("USG")["Sneak Attack"]), None
    )
    return g2s_game, g2s_alice, g2s_bob


def test_w3g2_sneak_attack_puts_a_creature_in_with_haste(set_pool, catalog_by_name):
    """The whole sentence, end to end: the creature arrives from hand and can
    attack the turn it did.

    The grant carries **no** printed duration, so CR 611.2a makes it last as
    long as the object — the layer-6 write API spells that as a ``None``
    lifetime, and a grant that quietly became "until end of turn" would be a
    different card the moment anything looked at it on a later turn.
    """
    game, alice, _bob = _g2s_sneak_attack_board(
        set_pool, hand=[catalog_by_name["Grizzly Bears"]]
    )

    assert game.activate_permanent_ability(0, "Sneak Attack").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    arrived = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert arrived.has_keyword("haste")
    assert not alice.hand


def test_w3g2_sneak_attack_sacrifices_it_at_the_next_end_step(set_pool, catalog_by_name):
    """CR 603.7c: the delayed ability is about the permanent *that* resolution
    put onto the battlefield, frozen by id when the ability was created.

    Nothing on the stack or on the board pointed at it — the card was in a hand
    when the ability was activated — so the binding is the only reading that
    can name it, and an unbound entry would answer to the first creature to be
    around at the end step.
    """
    game, alice, _bob = _g2s_sneak_attack_board(
        set_pool, hand=[catalog_by_name["Grizzly Bears"]]
    )
    game.activate_permanent_ability(0, "Sneak Attack")
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    game.resolve_end_step(0)
    resolve_stack(game)

    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Sneak Attack"]
    assert [c.name for c in alice.graveyard] == ["Grizzly Bears"]


def test_w3g2_sneak_attack_binds_the_creature_it_put_in_not_a_bystander(set_pool, catalog_by_name):
    """The binding tested against a board that can tell the two apart: another
    creature is already out, and only the one that arrived is sacrificed."""
    bystander = catalog_by_name["Hurloon Minotaur"]
    game, alice, _bob = _g2s_sneak_attack_board(
        set_pool, hand=[catalog_by_name["Grizzly Bears"]]
    )
    game._put_permanent_onto_battlefield(0, Permanent(card=bystander), None)

    game.activate_permanent_ability(0, "Sneak Attack")
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.resolve_end_step(0)
    resolve_stack(game)

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Hurloon Minotaur", "Sneak Attack",
    ]
    assert [c.name for c in alice.graveyard] == ["Grizzly Bears"]


def test_w3g2_sneak_attack_with_no_creature_in_hand_arms_nothing(set_pool, catalog_by_name):
    """The empty direction, which is the one a wrongly-True rider would break.

    Nothing was put onto the battlefield, so the record the two riders read is
    absent: the keyword grant finds nothing to grant to and the delayed ability
    has no permanent to be about, so **no** entry is armed. An unbound entry
    would answer to whatever creature happened to be around at the end step —
    the enchantment's controller sacrificing a bystander for a {R} they spent
    on nothing.
    """
    game, alice, _bob = _g2s_sneak_attack_board(
        set_pool, hand=[catalog_by_name["Mox Pearl"]]
    )
    game._put_permanent_onto_battlefield(
        0, Permanent(card=catalog_by_name["Hurloon Minotaur"]), None
    )

    game.activate_permanent_ability(0, "Sneak Attack")
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert not game.delayed_triggers

    game.resolve_end_step(0)
    resolve_stack(game)

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Hurloon Minotaur", "Sneak Attack",
    ]
    assert not alice.graveyard
    assert [c.name for c in alice.hand] == ["Mox Pearl"]


def test_w3g2_sneak_attack_only_offers_creature_cards(set_pool, catalog_by_name):
    """"a **creature** card from your hand" — the printed noun, enforced by the
    candidate rule the prompt and its default both read."""
    from engine.handlers.zones import put_from_hand_candidates

    game, alice, _bob = _g2s_sneak_attack_board(
        set_pool,
        hand=[catalog_by_name["Mox Pearl"], catalog_by_name["Grizzly Bears"]],
    )
    payload = {"card_filter": {"type_filter": "creature"}, "whose": "you"}

    assert put_from_hand_candidates(game, payload, alice) == [1]


# --- W3G3: Carpet of Flowers — a per-main-phase trigger and its mana record ---
import pytest

from engine import Game, PlayerState
from engine.game_types import Permanent


def _g3c_carpet_board(set_pool, *, islands=3, interactive=()):
    """Seat 0 has the Carpet; seat 1 has *islands* Islands."""
    pool = set_pool("USG")
    lea = set_pool("LEA")
    carpet = Permanent(card=pool["Carpet of Flowers"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[carpet]),
        PlayerState(name="P1",
                    battlefield=[Permanent(card=lea["Island"]) for _ in range(islands)]),
    ])
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game, carpet


def _g3c_settle(game):
    """Resolve the trigger and answer the prompts a non-interactive seat owes.

    Not `resolve_stack`: the offer this trigger arms does not block the stack,
    so the stack empties with the decision still owed.
    """
    while game.stack and game.resolve_top_of_stack():
        pass
    game.auto_resolve_pending_choices()


def _g3c_pool(game, seat=0):
    return {sym: n for sym, n in game.players[seat].mana_pool.items() if n}


def test_w3g3_carpet_adds_one_mana_per_opponent_island(set_pool):
    """"…add X mana of any one color, where X is the number of Islands target
    opponent controls." The count is the *opponent's* board, not this seat's."""
    game, _ = _g3c_carpet_board(set_pool, islands=3)

    game._enter_main_phase(precombat=True)
    _g3c_settle(game)

    assert sum(_g3c_pool(game).values()) == 3


def test_w3g3_carpet_fires_at_both_main_phases_but_adds_once(set_pool):
    """CR 505.1's two main phases are two firings; "if you haven't added mana
    with this ability this turn" is what makes only the first of them pay.

    The record is read twice (CR 603.4 checks an intervening-if when the trigger
    would fire and again at resolution), and it must not move between them.
    """
    game, carpet = _g3c_carpet_board(set_pool, islands=2)

    game._enter_main_phase(precombat=True)
    _g3c_settle(game)
    assert sum(_g3c_pool(game).values()) == 2

    game.players[0].mana_pool.update({sym: 0 for sym in game.players[0].mana_pool})
    game._enter_main_phase(precombat=False)
    _g3c_settle(game)

    assert _g3c_pool(game) == {}
    assert not game.stack


def test_w3g3_carpet_pays_again_on_the_next_turn(set_pool):
    """"This turn" is a turn stamp, so a new turn is a fresh record with nothing
    to clear."""
    game, _ = _g3c_carpet_board(set_pool, islands=2)

    game._enter_main_phase(precombat=True)
    _g3c_settle(game)
    game.players[0].mana_pool.update({sym: 0 for sym in game.players[0].mana_pool})

    game.turn += 1
    game._enter_main_phase(precombat=True)
    _g3c_settle(game)

    assert sum(_g3c_pool(game).values()) == 2


def test_w3g3_carpet_is_silent_on_an_opponents_turn(set_pool):
    """"Each of **your** main phases" — a main phase belongs to the active
    player, so an opponent's is not one of them."""
    game, _ = _g3c_carpet_board(set_pool, islands=2)
    game.turn += 1
    game.active_player_index = 1

    game._enter_main_phase(precombat=True)
    _g3c_settle(game)

    assert _g3c_pool(game) == {}


def test_w3g3_carpet_asks_an_interactive_seat_which_colour(set_pool):
    """"Add X mana of **any one color**" is CR 106.1b's choice, and a triggered
    ability carries no announcement to make it — so it is a prompt at
    resolution. Before this it fell through to a hard-coded green.
    """
    game, carpet = _g3c_carpet_board(set_pool, islands=2, interactive=(0,))

    game._enter_main_phase(precombat=True)
    while game.stack and game.resolve_top_of_stack():
        pass

    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, "Carpet of Flowers", accept=True)

    choice = game.pending_choices[0]
    assert choice.kind == "mana_color_choice"
    assert choice.data["colors"] == ["W", "U", "B", "R", "G"]
    assert choice.data["amount"] == 2
    assert _g3c_pool(game) == {}          # nothing until the colour is named

    assert game.confirm_mana_color_choice(0, "U") is True
    assert _g3c_pool(game) == {"U": 2}


def test_w3g3_a_colour_off_the_offer_is_refused_not_clamped(set_pool):
    """Idiom 9: the answer is re-checked against the list the picker was given,
    so a stale or invented colour is refused rather than rounded to a legal
    one."""
    game, _ = _g3c_carpet_board(set_pool, islands=1, interactive=(0,))

    game._enter_main_phase(precombat=True)
    while game.stack and game.resolve_top_of_stack():
        pass
    game.confirm_optional_pay(0, "Carpet of Flowers", accept=True)

    assert game.confirm_mana_color_choice(0, "purple") is False
    assert _g3c_pool(game) == {}
    assert game.pending_choices


def test_w3g3_carpet_with_no_opponent_island_adds_nothing(set_pool):
    """X is zero, so the offer produces no mana — and writes no record, which is
    what lets the postcombat firing still be a real offer."""
    game, carpet = _g3c_carpet_board(set_pool, islands=0)

    game._enter_main_phase(precombat=True)
    _g3c_settle(game)

    assert _g3c_pool(game) == {}
    from engine.mana_ability_records import MANA_ADDED_MARK
    assert not carpet.metadata.get(MANA_ADDED_MARK)


@pytest.mark.parametrize("precombat", [True, False])
def test_w3g3_the_condition_is_checked_before_the_trigger_goes_on_the_stack(
    set_pool, precombat
):
    """CR 603.4: a gated trigger whose condition is false **does not trigger**.

    It is not an ability that resolves to nothing — it holds no priority and
    nothing in response sees it — so the check lives at the fire site as well as
    at resolution.
    """
    from engine.mana_ability_records import (MANA_ADDED_WITH_THIS_ABILITY,
                                             note_mana_added)

    game, carpet = _g3c_carpet_board(set_pool, islands=3)
    note_mana_added(game, carpet, MANA_ADDED_WITH_THIS_ABILITY)

    game._enter_main_phase(precombat=precombat)

    assert not game.stack

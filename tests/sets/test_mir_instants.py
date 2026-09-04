"""Per-card tests for Mirage's instants.

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


# --- Round 2: phasing (CR 702.26) ---

import pytest

from engine import Game, PlayerState
from engine.models import Permanent


def _r2_ripple_board(set_pool, victim_name: str):
    """Reality Ripple in hand on seat 0, one permanent to aim it at on seat 1."""
    pool = set_pool("MIR")
    victim = Permanent(card=pool[victim_name])
    game = Game(players=[
        PlayerState(
            name="P1", hand=[pool["Reality Ripple"]],
            library=[pool["Island"]] * 6,
        ),
        PlayerState(name="P2", battlefield=[victim], library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, victim


@pytest.mark.parametrize(
    "victim_name", ["Sandbar Crocodile", "Island", "Charcoal Diamond"]
)
def test_reality_ripple_phases_out_all_three_printed_types(set_pool, victim_name):
    """"Target **artifact, creature, or land** phases out."

    The card was already reported supported, claimed every printed sentence and
    derived a correct picker — and the handler then declined two of the three
    types, because the type test was hardcoded to "creature" rather than read
    off the noun phrase the picker had already enumerated with. Nothing failed;
    the spell resolved and did nothing. That is the class only a game finds.
    """
    game, victim = _r2_ripple_board(set_pool, victim_name)

    result = game.cast_from_hand(
        0, "Reality Ripple", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert not game.is_on_battlefield(victim)
    assert victim in game.players[1].phased_out


def test_a_permanent_reality_ripple_phased_out_comes_back_once(set_pool):
    """The incoming half of CR 702.26a reads the holding list rather than the
    keyword, so a permanent with no phasing of its own returns exactly once and
    then stays."""
    game, victim = _r2_ripple_board(set_pool, "Island")
    game.cast_from_hand(
        0, "Reality Ripple", target_player_index=1, target_permanent_index=0
    )
    game.resolve_stack()

    game.start_turn(1)
    assert game.is_on_battlefield(victim)

    game.start_next_turn()
    game.start_next_turn()
    assert game.is_on_battlefield(victim)


# --- Round 6: a handler that pinned a type its card did not print ---

def test_disempower_tucks_either_of_its_printed_types(set_pool):
    """"Put target **artifact or enchantment** on top of its owner's library."

    Reality Ripple's defect, one file over and found the same way. The tuck
    lowering demanded ``card_types == ("creature",)`` and the handler asked
    ``is_creature`` — two copies of a narrowing the printed noun phrase does not
    have, on an effect that is the same for every permanent type: CR 400.3's
    owner lookup and the library move do not care what was moved.
    """
    pool = set_pool("MIR")
    for host_name in ("Charcoal Diamond", "Armor of Thorns"):
        host = Permanent(card=pool[host_name])
        game = Game(players=[
            PlayerState(name="P1", hand=[pool["Disempower"]],
                        library=[pool["Island"]] * 5),
            PlayerState(name="P2", battlefield=[host],
                        library=[pool["Island"]] * 5),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = set()
        result = game.cast_from_hand(
            0, "Disempower", target_player_index=1, target_permanent_index=0
        )
        assert result.supported, result.details
        game.resolve_stack()

        assert not game.is_on_battlefield(host)
        assert game.players[1].library[0].name == host_name


def test_disempower_still_refuses_a_creature(set_pool):
    """The narrowing is carried, not dropped — which is the other half of the
    fix. Widening the lowering to any noun phrase would be worth nothing if the
    handler then moved whatever it was handed."""
    pool = set_pool("MIR")
    creature = Permanent(card=pool["Femeref Knight"])
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Disempower"]], library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=[creature], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.cast_from_hand(
        0, "Disempower", target_player_index=1, target_permanent_index=0
    )
    game.resolve_stack()

    assert game.is_on_battlefield(creature)


# --- Round 9: the tutor cycle (CR 701.19 / 701.23) ---

from engine.search_filters import search_matches


def _r9_tutor(set_pool, spell: str, library_names: list[str]):
    """*spell* cast on seat 0 over a library built from *library_names*."""
    pool = set_pool("MIR")
    game = Game(players=[
        PlayerState(
            name="P1", hand=[pool[spell]],
            library=[pool[name] for name in library_names],
        ),
        PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    result = game.cast_from_hand(0, spell)
    assert result.supported, result.details
    game.resolve_stack()
    (choice,) = game.pending_choices
    assert choice.kind == "search_library"
    return game, choice


_R9_LIBRARY = [
    "Island", "Femeref Knight", "Charcoal Diamond", "Armor of Thorns", "Island",
]


def test_enlightened_tutor_finds_either_of_its_two_types(set_pool):
    """"Search your library for an **artifact or enchantment** card…"

    A printed union is an OR — the reading `any_colors` beside it already gets,
    and the one every noun-phrase matcher in this engine gives a multi-type
    filter. The lowering used to refuse a union outright ("the search picker
    tests one card type"), which was the safe direction and cost all three
    tutors their cards.
    """
    _game, choice = _r9_tutor(set_pool, "Enlightened Tutor", _R9_LIBRARY)

    assert choice.data["card_type"] == ("artifact", "enchantment")
    assert choice.data["destination"] == "library_top"


def test_enlightened_tutor_offers_only_the_matching_cards(set_pool):
    """The union narrows the search; it does not widen it."""
    game, choice = _r9_tutor(set_pool, "Enlightened Tutor", _R9_LIBRARY)

    legal = {
        card.name for card in game.players[0].library
        if search_matches(card, choice.data)
    }

    assert legal == {"Charcoal Diamond", "Armor of Thorns"}


def test_a_tutor_puts_its_find_on_top_after_the_shuffle(set_pool):
    """"…, reveal it, **then shuffle and put that card on top**."

    The order is the effect. Placing the find first and then shuffling — which
    is what falling through to the shared shuffle would do — is the card doing
    nothing at all, so the destination branch shuffles itself and returns.
    """
    game, _choice = _r9_tutor(set_pool, "Worldly Tutor", _R9_LIBRARY)
    index = next(
        i for i, card in enumerate(game.players[0].library)
        if card.name == "Femeref Knight"
    )

    assert game.confirm_search_library(0, index)

    assert game.players[0].library[0].name == "Femeref Knight"
    assert len(game.players[0].library) == len(_R9_LIBRARY)


# --- W1G4: the zones / cards / library family ---

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent


def _w1g4_duel(pool, *, seat0_hand=(), seat1_battlefield=(), seat1_hand=(),
               seat1_library=("Island",) * 5):
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", hand=[pool[n] for n in seat0_hand],
            library=[pool["Island"]] * 5,
        ),
        _W1G4PlayerState(
            name="P2",
            battlefield=[_W1G4Permanent(card=pool[n]) for n in seat1_battlefield],
            hand=[pool[n] for n in seat1_hand],
            library=[pool[n] for n in seat1_library],
        ),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    return game


def test_afterlife_gives_the_token_to_the_destroyed_creatures_controller(set_pool):
    """"Destroy target creature. It can't be regenerated. **Its controller**
    creates a 1/1 white Spirit creature token with flying."

    The rider is the one Angelic Ascension prints behind an *exile*, and it
    refused here for want of a producer -- while the destroy handler had been
    recording exactly that seat all along, under a second name. The assertion
    that matters is whose battlefield the Spirit lands on: reading the
    ability's own controller would have handed it to the caster.
    """
    pool = set_pool("MIR")
    game = _w1g4_duel(
        pool, seat0_hand=("Afterlife",), seat1_battlefield=("Femeref Scouts",)
    )
    game.start_turn(0)

    result = game.cast_from_hand(
        0, "Afterlife", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert [c.name for c in game.players[1].graveyard] == ["Femeref Scouts"]
    assert game.players[0].battlefield == [], "the caster gets nothing"
    spirits = [p for p in game.players[1].battlefield if p.card.name == "Spirit Token"]
    assert len(spirits) == 1
    assert spirits[0].card.colors == ("W",)
    assert "Flying" in spirits[0].card.keywords


def test_afterlife_creates_nothing_when_the_destroy_chose_nothing(set_pool):
    """CR 608.2b: the rider names the object the previous step chose, so with no
    target chosen there is no controller for the sentence to name and no token.

    The gate is the producer record's absence rather than a branch in the token
    handler, which is what keeps "does as much as it can" from inventing a seat.
    """
    pool = set_pool("MIR")
    game = _w1g4_duel(pool, seat0_hand=("Afterlife",))
    game.start_turn(0)

    game.cast_from_hand(0, "Afterlife")
    game.resolve_stack()

    assert game.players[0].battlefield == []
    assert game.players[1].battlefield == []


def test_illumination_heals_the_countered_spells_controller_for_its_mana_value(set_pool):
    """"Counter target artifact or enchantment spell. **Its controller** gains
    life equal to **its mana value**."

    Both halves name the countered spell, and by the time the second sentence
    runs it is a card in a graveyard: CR 108.4 gives that no controller and
    CR 613.1 no characteristics, so both are read off records the counter wrote
    (CR 608.2h). The life goes to the *opponent* -- the payload used to say
    ``recipient: "target"``, which for a counterspell is the spell.
    """
    pool = set_pool("MIR")
    game = _w1g4_duel(pool, seat0_hand=("Illumination",), seat1_hand=("Mana Prism",))
    game.start_turn(1)
    assert game.queue_from_hand(1, "Mana Prism").supported
    assert [item.card.name for item in game.stack] == ["Mana Prism"]

    result = game.cast_from_hand(0, "Illumination", target_stack_index=0)
    assert result.supported, result.details
    game.resolve_stack()

    assert [c.name for c in game.players[1].graveyard] == ["Mana Prism"]
    assert game.players[1].life == 23, "Mana Prism costs {3}"
    assert game.players[0].life == 20, "the caster heals nobody"


def test_illumination_gains_no_life_when_it_counters_nothing(set_pool):
    """With nothing countered there is no spell for either possessive to name,
    so no life is gained -- rather than the caster's own total moving, which is
    what a recipient defaulted to "caster" would have done."""
    pool = set_pool("MIR")
    game = _w1g4_duel(pool, seat0_hand=("Illumination",))
    game.start_turn(0)

    game.cast_from_hand(0, "Illumination")
    game.resolve_stack()

    assert (game.players[0].life, game.players[1].life) == (20, 20)


# --- W1G3: damage / prevention / life ---

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent


def _w1g3_destroy_rider(set_pool, spell, victim_name, **kwargs):
    pool = set_pool("MIR")
    victim = _W1G3Permanent(card=pool[victim_name])
    p1 = _W1G3PlayerState(name="P1", hand=[pool[spell]],
                          library=[pool["Island"]] * 5, life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[victim],
                          library=[pool["Island"]] * 5, life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(
        0, spell, target_player_index=1, target_permanent_index=0, **kwargs
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()
    return game, p1, p2, victim


def test_cinder_cloud_burns_only_for_a_white_creature(set_pool):
    """"Destroy target creature. **If a white creature dies this way**, Cinder
    Cloud deals damage to that creature's controller equal to the creature's
    power."

    The rider names the destroy family's own record, so it is the same set
    "for each creature that died this way" iterates — and lowering it to that
    loop is what gives the arm its per-object reads. An "if" is not a "for
    each" in general, so the reading is admitted only after a *single-target*
    destroy, where the record can hold at most one object.
    """
    game, p1, p2, victim = _w1g3_destroy_rider(
        set_pool, "Cinder Cloud", "Zhalfirin Commander"      # white 2/2
    )

    assert not game.is_on_battlefield(victim)
    assert p2.life == 18, f"2 power to its controller: {game.log}"


def test_cinder_cloud_kills_a_nonwhite_creature_without_burning(set_pool):
    """The colour narrowing, which the loop's iterator refused to carry until
    this round — it read the printed card type and nothing else."""
    game, p1, p2, victim = _w1g3_destroy_rider(
        set_pool, "Cinder Cloud", "Cadaverous Knight"        # black 2/2
    )

    assert not game.is_on_battlefield(victim)
    assert p2.life == 20, f"only a white creature pays: {game.log}"


def test_kaerveks_purge_burns_for_whatever_it_destroyed(set_pool):
    """"Destroy target creature with mana value X. **If that creature dies this
    way**, Kaervek's Purge deals damage equal to the creature's power to the
    creature's controller."

    The bound spelling of Cinder Cloud's rider, with no colour on it — and the
    definite article on both possessives, which the amount reader had never
    seen ("that creature's power" was the only spelling it took).
    """
    pool = set_pool("MIR")
    victim = _W1G3Permanent(card=pool["Wild Elephant"])      # 3/3, mv 4
    p1 = _W1G3PlayerState(name="P1", hand=[pool["Kaervek's Purge"]],
                          library=[pool["Island"]] * 5, life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[victim],
                          library=[pool["Island"]] * 5, life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    result = game.cast_from_hand(
        0, "Kaervek's Purge", x_value=4,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(victim)
    assert p2.life == 17, f"3 power to its controller: {game.log}"


def test_kaerveks_purge_burns_for_nothing_when_the_creature_regenerates(set_pool):
    """"If that creature dies this way" is a *record of what actually died*
    (CR 701.8c), not of what the spell aimed at — a regenerated creature was
    never destroyed, so the rider finds nothing to burn for."""
    pool = set_pool("MIR")
    victim = _W1G3Permanent(card=pool["Cadaverous Knight"])  # regenerate, mv 3
    victim.regeneration_shield = 1
    p1 = _W1G3PlayerState(name="P1", hand=[pool["Kaervek's Purge"]],
                          library=[pool["Island"]] * 5, life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[victim],
                          library=[pool["Island"]] * 5, life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    result = game.cast_from_hand(
        0, "Kaervek's Purge", x_value=3,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert game.is_on_battlefield(victim), "the shield saved it"
    assert p2.life == 20, f"nothing died this way: {game.log}"


def _w1g3_shadowbane(set_pool, source_name):
    """Cast Shadowbane naming *source_name* on the opponent's board."""
    pool = set_pool("MIR")
    mine = _W1G3Permanent(card=pool["Zhalfirin Commander"])
    threat = _W1G3Permanent(card=pool[source_name])
    p1 = _W1G3PlayerState(name="P1", battlefield=[mine],
                          hand=[pool["Shadowbane"]],
                          library=[pool["Island"]] * 5, life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[threat],
                          library=[pool["Island"]] * 5, life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(
        0, "Shadowbane", target_player_index=1,
        target_permanent_ids=[threat.permanent_id],
    )
    assert result.supported, result.details
    game.resolve_stack()
    return game, p1, p2, mine, threat


def test_shadowbane_shields_a_creature_its_caster_controls(set_pool):
    """"The next time a source of your choice would deal damage to **you
    and/or creatures you control** this turn, prevent that damage."

    The first shield in the pool whose recipient is a player *and* a described
    set. A shield lives on the object it protects, and a phrase is not an
    object — the creatures it covers include ones that have not entered yet —
    so it lives on the seat and is matched against each damaged permanent, the
    shape the redirect side has had since Blood of the Martyr.
    """
    from tests.helpers import _damage_dealt

    game, p1, p2, mine, threat = _w1g3_shadowbane(set_pool, "Cadaverous Knight")

    assert _damage_dealt(game, mine, 4, source=threat) == 0, (
        f"the creature is covered by the phrase: {game.log}"
    )


def test_shadowbane_pays_life_only_for_a_black_source(set_pool):
    """"**If damage from a black source is prevented this way**, you gain that
    much life."

    The condition is a property of the *source*, so it rides beside the
    shield's own rather than inside it: the card prevents every colour's damage
    and pays for one. And the life goes to the caster, not to the creature that
    was about to be damaged.
    """
    from tests.helpers import _damage_dealt

    game, p1, p2, mine, threat = _w1g3_shadowbane(set_pool, "Cadaverous Knight")
    assert _damage_dealt(game, p1, 3, source=threat) == 0
    game._settle()

    assert p1.life == 23, f"a black source pays: {game.log}"


def test_shadowbane_prevents_without_paying_for_a_nonblack_source(set_pool):
    """The other direction — the shield still applies, the rider does not."""
    from tests.helpers import _damage_dealt

    game, p1, p2, mine, threat = _w1g3_shadowbane(set_pool, "Azimaet Drake")
    assert _damage_dealt(game, p1, 3, source=threat) == 0
    game._settle()

    assert p1.life == 20, f"a blue source prevents but does not pay: {game.log}"


def test_shadowbane_waits_for_the_source_it_chose(set_pool):
    """Without this the tests above pass for a shield that answers to
    everything — and a one-shot shield spent on the wrong event is gone."""
    from tests.helpers import _damage_dealt

    pool = set_pool("MIR")
    mine = _W1G3Permanent(card=pool["Zhalfirin Commander"])
    named = _W1G3Permanent(card=pool["Cadaverous Knight"])
    other = _W1G3Permanent(card=pool["Azimaet Drake"])
    p1 = _W1G3PlayerState(name="P1", battlefield=[mine],
                          hand=[pool["Shadowbane"]],
                          library=[pool["Island"]] * 5, life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[named, other],
                          library=[pool["Island"]] * 5, life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    assert game.cast_from_hand(
        0, "Shadowbane", target_player_index=1,
        target_permanent_ids=[named.permanent_id],
    ).supported
    game.resolve_stack()

    assert _damage_dealt(game, mine, 2, source=other) == 2
    assert _damage_dealt(game, mine, 2, source=named) == 0


def test_shadowbane_does_not_shield_an_opponents_creature(set_pool):
    """"creatures **you** control" is the caster's "you" (CR 109.5), captured
    when the shield was armed — the resolution is long over by damage time."""
    from tests.helpers import _damage_dealt

    game, p1, p2, mine, threat = _w1g3_shadowbane(set_pool, "Cadaverous Knight")

    assert _damage_dealt(game, threat, 2, source=threat) == 2, (
        f"the phrase names the caster's creatures: {game.log}"
    )


# --- W1G1: the combat family ---
#
# Yare is the instant half of the combat group: CR 509.1b's block-count ceiling
# raised rather than tightened, which is the one direction the combat
# productions did not read.

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g1i_creature(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g1i_nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g1i_combat(set_pool, attackers: int = 3):
    """Seat 0 attacking with *attackers* creatures into seat 1's lone Defender,
    with Yare in seat 1's hand and the attack already declared."""
    raiders = [
        _w1g1i_nosick(Permanent(card=_w1g1i_creature(f"Raider{i}", 1, 1)))
        for i in range(attackers)
    ]
    defender = _w1g1i_nosick(Permanent(card=_w1g1i_creature("Defender", 2, 6)))
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(raiders)),
        PlayerState(name="P2", battlefield=[defender], hand=[set_pool("MIR")["Yare"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, list(range(attackers)))[0]
    return game, defender


def test_yare_compiles_both_of_its_sentences(set_pool):
    """The second sentence's "that creature" is the bound object the first one
    targeted, not a second choice -- so it emits no target description of its
    own and the handler acts on the spell's one target, the idiom
    ``lowering/keywords.py`` established for the identical pronoun."""
    program = compile_card_oracle(set_pool("MIR")["Yare"])
    assert program.supported, program.reason
    (sequence, _pattern) = program.instructions
    steps = sequence.payload["steps"]
    assert [step.kind for step in steps] == [
        "pump_target_creature_until_eot", "grant_additional_blocks_until_eot",
    ]
    assert steps[1].payload == {"count": 2}


def test_yare_lets_one_creature_block_three(set_pool):
    """CR 509.1b's ceiling raised by two. The permission **adds** to the
    printed default rather than replacing it -- a creature blocks one attacker
    to begin with, so "up to two additional" is three."""
    game, defender = _w1g1i_combat(set_pool)
    assert game._max_blocks_for(defender) == 1

    result = game.cast_from_hand(
        1, "Yare", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert (defender.effective_power, defender.effective_toughness) == (5, 6)
    assert game._max_blocks_for(defender) == 3

    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: [0, 1, 2]})[0]


def test_yare_ends_with_the_turn(set_pool):
    """"…this turn" is the sweep, and the sweep is what says so: a granted
    combat permission nothing clears is a permanent one. Blaze of Glory's two
    flags had exactly that hole -- written by a handler, read by the blockers
    step and by the AI, swept by nothing -- and were found by putting this
    count beside them."""
    game, defender = _w1g1i_combat(set_pool)
    assert game.cast_from_hand(
        1, "Yare", target_player_index=1, target_permanent_index=0
    ).supported
    game.resolve_stack()
    game._settle()
    assert game._max_blocks_for(defender) == 3

    game.resolve_cleanup_step(0)

    assert game._max_blocks_for(defender) == 1


def test_yare_is_uncastable_with_no_combat(set_pool):
    """"Target creature **defending player controls**" outside combat names a
    seat that does not exist (CR 506.2), so the spell has no legal target.

    That is the answer rather than a fallback, and it is the half of the
    defending-player narrowing a *spell* needed: a trigger's announcement
    freezes the seat because its combat may be over by resolution, and a spell
    has no such record because it is being cast right now.
    """
    defender = _w1g1i_nosick(Permanent(card=_w1g1i_creature("Defender", 2, 6)))
    game = Game(players=[
        PlayerState(name="P1"),
        PlayerState(name="P2", battlefield=[defender],
                    hand=[set_pool("MIR")["Yare"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.cast_from_hand(
        1, "Yare", target_player_index=1, target_permanent_index=0
    )
    assert not result.supported
    assert game._max_blocks_for(defender) == 1


def test_yare_does_not_reach_the_attacking_players_creatures(set_pool):
    """The narrowing the picker had no way to answer, and which the pump
    handler dropped on the other side: "defending player controls" is a seat,
    and both ends now read the live combat's."""
    game, _defender = _w1g1i_combat(set_pool)

    result = game.cast_from_hand(
        1, "Yare", target_player_index=0, target_permanent_index=0
    )
    assert not result.supported, "an attacker is not a creature the defender controls"


# --- W1G5: the statics / characteristics / control family ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _g5_vanilla(name: str, power: int = 2, toughness: int = 2,
                type_line: str = "Creature - Test") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _g5_game(pool, hand, battlefield=(), opponent=()):
    game = Game(players=[

        PlayerState(name="P1", hand=[pool[name] for name in hand],
                    battlefield=list(battlefield),
                    library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=list(opponent),
                    library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_dissipate_exiles_the_spell_it_counters(set_pool):
    """"Counter target spell. If that spell is countered this way, **exile it**
    instead of putting it into its owner's graveyard."

    CR 614.1 replacing CR 701.5a's destination, which Memory Lapse's production
    already carried — written with the destination as a *verb* rather than a
    zone, because "put it into exile" is not a sentence Magic uses. One branch
    of that production rather than a second one: the "instead of … graveyard"
    tail is the whole rest of the clause, and a second production would be a
    second place to forget the word that makes this a replacement at all.
    """
    pool = set_pool("MIR")
    game = _g5_game(pool, ["Dissipate"])
    game.players[1].hand.append(pool["Mangara's Blessing"])
    before = game.players[1].life

    game.queue_from_hand(1, "Mangara's Blessing")
    counter = game.cast_from_hand(0, "Dissipate", target_stack_index=0)
    assert counter.supported, counter.details
    game.resolve_stack()

    # Both halves, because the failure a dropped destination clause causes is
    # silent: the card in the graveyard is exactly what a plain Counterspell
    # leaves behind and reads as nothing having gone wrong.
    assert game.players[1].life == before, "the spell was countered"
    assert [card.name for card in game.players[1].graveyard] == []
    assert [getattr(card, "name", card) for card in game.players[1].exile] == [
        "Mangara's Blessing"
    ]


def test_prismatic_boon_protects_every_creature_it_named(set_pool):
    """"Choose a color. **X** target creatures gain protection from **the chosen
    color** until end of turn."

    "The chosen color" is the same question "the color of your choice" asks —
    CR 609.3 puts both in this resolution, so they name one colour and read one
    channel. A second keyword string would have been a second answer to it, and
    the grant handler would have had to learn which sentence had done the
    asking.
    """
    a = Permanent(card=_g5_vanilla("A"))
    b = Permanent(card=_g5_vanilla("B"))
    game = _g5_game(set_pool("MIR"), ["Prismatic Boon"], battlefield=[a, b])

    cast = game.cast_from_hand(
        0, "Prismatic Boon", x_value=2, new_color="R",
        target_permanent_ids=[a.permanent_id, b.permanent_id],
    )
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert game._protection_colors(a) == {"R"}
    assert game._protection_colors(b) == {"R"}


def test_prismatic_lace_offers_a_set_of_colours(set_pool):
    """"Target permanent becomes the color **or colors** of your choice."

    The one subject of the three that had no path to the set offer: the Aura's
    host and the source itself both reached ``arm_color_set_choice`` and a
    *target* refused outright. Asked as a prompt rather than read off the
    activation's single symbol, because one symbol is a legal answer to the
    offer and not the offer itself — taking it would quietly make "or colors"
    mean "a color" on every printing.
    """
    host = Permanent(card=_g5_vanilla("Statue", 1, 1, "Artifact Creature - Golem"))
    game = _g5_game(set_pool("MIR"), ["Prismatic Lace"], battlefield=[host])

    cast = game.cast_from_hand(0, "Prismatic Lace",
                               target_player_index=0, target_permanent_index=0)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    # A non-interactive seat takes the prompt's stated default at once, which
    # is a colour — the point being that a colour was *asked for* rather than
    # read off a cast that never named one.
    assert game._effective_colors(host), "a colour was chosen and written"


def test_a_counter_on_it_lands_on_what_the_sentence_before_chose():
    """"Gain control of target creature. **Put a -1/-0 counter on it.**"

    A bare "it" is the ability's own source everywhere else, which is what
    ``parse_recipient`` reads — so this sentence lowered to
    ``add_counter_to_self`` and the counter went on the wrong permanent, or,
    for a spell, on nothing at all. Neither raises, which is why the rider
    exists.
    """
    from engine.grammar import compile_line

    result = compile_line(
        "Gain control of target creature. Put a -1/-0 counter on it."
    )
    kinds = [instruction.kind for instruction in result.instructions]
    assert kinds == ["gain_control_of_target", "add_counter_to_target"]


def test_the_pronoun_rider_leaves_a_named_subject_alone():
    """"Put a +1/+1 counter on **this creature**" is not the pronoun, and keeps
    its own referent — the rider fires on ``quantifier == "it"`` alone."""
    from engine.grammar import compile_line

    result = compile_line("Tap target creature. Put a +1/+1 counter on this creature.")
    kinds = [instruction.kind for instruction in result.instructions]
    assert kinds == ["tap_target_permanent", "add_counter_to_self"]


def test_ersatz_gnomes_can_be_aimed(set_pool):
    """"{T}: Target permanent becomes colorless until end of turn."

    A supported card no player could use. The recolour lowering described its
    targets only for the "one or more target creatures" spelling — the *single*
    target got no description at all, so ``derive_activation_spec`` had no
    evidence and the picker offered nothing. The handler reads neither
    description: it resolves through ``resolve_target_permanents``, which asks
    the resolution what was chosen, so the missing half was invisible to every
    test that gave the ability a target by hand.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    pool = set_pool("MIR")
    program = compile_card_oracle(pool["Ersatz Gnomes"])
    recolour = next(
        ability for ability in program.activated_abilities
        if ability.instruction is not None
        and ability.instruction.kind == "recolor_targets_until_eot"
    )
    assert derive_activation_spec(recolour) == {"kind": "permanent"}


def test_soul_rend_actually_destroys_a_white_creature(set_pool):
    """"Destroy target creature if it's white. A creature destroyed this way
    can't be regenerated."

    The card was *supported* and did nothing but draw its cantrip: the effect
    line refused as a whole — CR 701.15c's rider is read by the destroy
    production only when it trails the verb directly, and the sentence layer had
    already wrapped this destroy in the "if it's white" conditional — and a
    ``spell_pattern`` whitelist marker claimed the card anyway.
    """
    pool = set_pool("MIR")
    white = Permanent(card=CardDefinition(
        name="Cleric", mana_cost="", cmc=0.0, type_line="Creature - Human Cleric",
        oracle_text="", colors=("W",), color_identity=("W",), keywords=(),
        produced_mana=(),
        raw={"name": "Cleric", "type_line": "Creature - Human Cleric",
             "power": "2", "toughness": "2", "colors": ["W"]},
    ))
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Soul Rend"]],
                    library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=[white],
                    library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    cast = game.cast_from_hand(0, "Soul Rend", target_player_index=1,
                               target_permanent_index=0)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(white)


def test_soul_rend_spares_a_creature_of_another_colour(set_pool):
    """The condition half. Read as an unconditional destroy the card would be
    strictly better than the one printed."""
    pool = set_pool("MIR")
    green = Permanent(card=CardDefinition(
        name="Wurm", mana_cost="", cmc=0.0, type_line="Creature - Wurm",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": "Wurm", "type_line": "Creature - Wurm",
             "power": "4", "toughness": "4", "colors": ["G"]},
    ))
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Soul Rend"]],
                    library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=[green],
                    library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.cast_from_hand(0, "Soul Rend", target_player_index=1,
                        target_permanent_index=0)
    game.resolve_stack()
    game._settle()

    assert game.is_on_battlefield(green)


def test_early_harvest_untaps_the_seat_the_caster_chose(set_pool):
    """"**Target player** untaps all basic lands they control."

    Both halves were missing and each hid the other. The noun phrase records
    the printed subject as ``controller: "that_player"``, which the picker was
    never told about — so the client sent a bare cast; and the handler read that
    seat only out of a *trigger's* frozen context (CR 603.10), so even a cast
    that named one untapped nothing at all and still went to the graveyard.
    """
    pool = set_pool("MIR")

    def _tapped(card):
        permanent = Permanent(card=card)
        permanent.tapped = True
        return permanent

    mine = _tapped(pool["Forest"])
    basic = _tapped(pool["Island"])
    nonbasic = _tapped(pool["Bad River"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[mine], hand=[pool["Early Harvest"]],
                    library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=[basic, nonbasic],
                    library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    cast = game.cast_from_hand(0, "Early Harvest", target_player_index=1)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not basic.tapped, "the chosen seat's basic land untaps"
    assert nonbasic.tapped, "'basic' is a supertype the sweep still tests"
    assert mine.tapped, "the caster's own board is not the target's"


def _g5_edict_board(set_pool):
    """Seat 0 with a Forest of its own and seat 1 with an Island."""
    pool = set_pool("MIR")
    mine = Permanent(card=pool["Forest"])
    theirs = Permanent(card=pool["Island"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[mine],
                    hand=[pool["Telim'Tor's Edict"]],
                    library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=[theirs],
                    library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    return game, mine, theirs


def test_telimtors_edict_exiles_a_permanent_you_own_and_control(set_pool):
    """"Exile target permanent you **own or control**."

    The union of two relations, which no single ``ObjectFilter`` field states
    and no *pair* of them states either: setting both is Obelisk of Undoing's
    "own **and** control", the intersection, which is the smaller set this card
    is printed to be larger than.
    """
    game, mine, _theirs = _g5_edict_board(set_pool)

    cast = game.cast_from_hand(0, "Telim'Tor's Edict",
                               target_player_index=0, target_permanent_index=0)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(mine)


def test_telimtors_edict_declines_a_permanent_that_is_neither(set_pool):
    """The narrowing, which was enforced in no place at all: the picker's spec
    for this kind carries no filter, and the exile handler asked the *pure*
    matcher — which cannot answer a question about a seat and therefore drops
    it. The Edict exiled anything on the table."""
    game, _mine, theirs = _g5_edict_board(set_pool)

    game.cast_from_hand(0, "Telim'Tor's Edict",
                        target_player_index=1, target_permanent_index=0)
    game.resolve_stack()
    game._settle()

    assert game.is_on_battlefield(theirs)


def test_telimtors_edict_reaches_a_permanent_you_control_but_do_not_own(set_pool):
    """The half "you control" alone would have covered and "you own" alone
    would not — and the card prints both, so a stolen permanent is a legal
    target for its thief. It still goes to its **owner's** exile (CR 400.3)."""
    from engine.control import change_control

    game, _mine, theirs = _g5_edict_board(set_pool)
    change_control(theirs, 0, source="test")
    game._sync_control()
    game._settle()

    index = [p.card.name for p in game.players[0].battlefield].index("Island")
    cast = game.cast_from_hand(0, "Telim'Tor's Edict",
                               target_player_index=0, target_permanent_index=index)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(theirs)
    assert [getattr(card, "name", card) for card in game.players[1].exile] == ["Island"]


# --- W1G2: "that turn's end step" is not the next end step there is ---

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.oracle import compile_card_oracle


def _w1g2_fortune_duel(set_pool, copies=2):
    game = Game(players=[
        PlayerState(
            name="P1",
            hand=[set_pool("MIR")["Final Fortune"] for _ in range(copies)],
            life=20,
        ),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def test_final_fortune_does_not_end_the_turn_it_was_cast_in(set_pool):
    """"Take an extra turn after this one. At the beginning of **that turn's**
    end step, you lose the game."

    "That turn" is the turn the sentence in front of it queued (CR 500.7 puts it
    directly after this one), so it is neither ``next_end_step`` — the next end
    step there is, which on a main-phase cast is *this* turn's — nor
    ``controllers_next_end_step``. Its own delayed event, announced only on an
    extra turn.
    """
    program = compile_card_oracle(set_pool("MIR")["Final Fortune"])
    assert program.supported, program.reason

    game = _w1g2_fortune_duel(set_pool)
    assert game.cast_from_hand(0, "Final Fortune").supported
    game.resolve_stack()
    assert game.extra_turn_queue == [0], game.log

    game.resolve_end_step(0)
    game.resolve_stack()

    assert not game.players[0].lost, game.log


def test_final_fortune_ends_the_extra_turn_it_bought(set_pool):
    """The other half of the same assertion — a delay nothing announces is an
    ability that waits forever, which is what this event would be without the
    end step's fire site."""
    game = _w1g2_fortune_duel(set_pool)
    game.cast_from_hand(0, "Final Fortune")
    game.resolve_stack()
    game.resolve_end_step(0)
    game.resolve_stack()

    game.start_next_turn()
    assert game.current_turn_is_extra
    game.resolve_end_step(game.active_player_index)
    game.resolve_stack()

    assert game.players[0].lost, game.log


def test_a_second_final_fortune_does_not_fire_in_the_turn_it_was_cast(set_pool):
    """The card's whole use is chaining, so the second copy is cast **during**
    an extra turn — the very turn whose end step is about to be announced.

    ``delayed_triggers.EVENTS_AFTER_THIS_TURN`` is what keeps that entry
    waiting: it names a turn the creating effect had only just queued, so the
    announcement made in its own turn is not the one it is for. Without the
    guard the chain would end the game a full turn early.
    """
    game = _w1g2_fortune_duel(set_pool)
    game.cast_from_hand(0, "Final Fortune")
    game.resolve_stack()
    game.resolve_end_step(0)
    game.resolve_stack()
    game.start_next_turn()

    extra_turn = game.turn
    game.cast_from_hand(0, "Final Fortune")
    game.resolve_stack()
    entries = [e for e in game.delayed_triggers
               if e.event == "granted_extra_turns_end_step"]
    assert len(entries) == 2, entries
    assert {e.armed_turn for e in entries} == {extra_turn - 1, extra_turn}

    game.resolve_end_step(game.active_player_index)
    game.resolve_stack()

    # The first copy's ability fires here — this is the turn it bought. The
    # second is still waiting for the turn *it* bought.
    still_waiting = [e for e in game.delayed_triggers
                     if e.event == "granted_extra_turns_end_step"]
    assert len(still_waiting) == 1, game.log
    assert still_waiting[0].armed_turn == extra_turn


def test_that_turn_refuses_without_a_grant_in_front_of_it(set_pool):
    """A back-reference with no producer names nothing, and the ability it would
    arm answers to an event that only ever happens on somebody's extra turn — so
    it would sit on the waiting list for the rest of the game while the card
    compiled clean."""
    result = compile_line(
        "At the beginning of that turn's end step, you lose the game.",
        card_name="Invented Card",
    )
    assert result.parse_error is None
    assert result.lowering_error is not None
    assert "granted an extra turn" in result.lowering_error


# --- W1G2: a permanent an earlier step created, named by the sentences behind it ---
#
# Shallow Grave and Zirilan of the Claw print one tail — "That <noun> gains
# haste until end of turn. Exile it at the beginning of the next end step." —
# about a permanent *no target chose*: the ability's subject is a card in a
# graveyard or a library, and the permanent does not exist until the step in
# front of the tail runs.
#
# The quoted-ability grant has read that record since Dreams of the Dead; the
# keyword grant refused the subject outright, and the exile read the pronoun as
# the ability's own source — which for a spell is the card itself, so it exiled
# nothing at all and compiled clean doing it.

from engine.models import Permanent


def _w1g2_grave_duel(set_pool, graveyard):
    game = Game(players=[
        PlayerState(
            name="P1",
            hand=[set_pool("MIR")["Shallow Grave"]],
            graveyard=[set_pool("MIR")[name] for name in graveyard],
            life=20,
        ),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def test_shallow_grave_takes_the_top_creature_card(set_pool):
    """"Return **the top creature card** of your graveyard to the battlefield."

    CR 404.3 makes a graveyard an ordered zone and CR 400.4 appends what
    arrives, so the top card is the most recent one — and "the top *creature*
    card" is the most recent of those. Nobody chooses, which is why the phrase
    gets its own quantifier rather than being read as a target the card never
    offered: a picker here would let the caster take whichever creature they
    liked.
    """
    program = compile_card_oracle(set_pool("MIR")["Shallow Grave"])
    assert program.supported, program.reason

    game = _w1g2_grave_duel(
        set_pool, ["Femeref Scouts", "Kaervek's Torch", "Viashino Warrior"]
    )
    assert game.cast_from_hand(0, "Shallow Grave").supported
    game.resolve_stack()

    returned = [p.card.name for p in game.players[0].battlefield]
    assert returned == ["Viashino Warrior"], game.log


def test_shallow_grave_grants_haste_to_what_it_returned(set_pool):
    """"**That creature** gains haste until end of turn."

    Not a target — the spell's subject was a *card* — so the grant reads the
    record the return wrote. Refused before this round with "unsupported
    keyword-grant subject", which is one printed pronoun with two answers: the
    quoted-ability grant beside it had read the same record for two sets.
    """
    game = _w1g2_grave_duel(set_pool, ["Viashino Warrior"])
    game.cast_from_hand(0, "Shallow Grave")
    game.resolve_stack()

    returned = game.players[0].battlefield[0]
    assert game._has_keyword(returned, "haste"), game.log


def test_shallow_grave_exiles_what_it_returned_not_itself(set_pool):
    """"**Exile it** at the beginning of the next end step."

    The pronoun reads as the ability's own source everywhere else, and here the
    source is an instant — so ``exile_self`` exiled nothing while the card
    reported itself supported. What it names is the permanent the first step
    put onto the battlefield, and the id is frozen when the delayed ability is
    *created* (CR 603.7c): by the time it fires, the resolution's scratchpad is
    long gone.
    """
    game = _w1g2_grave_duel(set_pool, ["Viashino Warrior"])
    game.cast_from_hand(0, "Shallow Grave")
    game.resolve_stack()
    returned_id = game.players[0].battlefield[0].permanent_id
    armed = [e for e in game.delayed_triggers if e.event == "next_end_step"]
    assert [e.bound_permanent_id for e in armed] == [returned_id], game.log

    game.resolve_end_step(0)
    game.resolve_stack()

    assert game.players[0].battlefield == [], game.log
    assert [c.name for c in game.players[0].exile] == ["Viashino Warrior"], game.log


def test_shallow_grave_with_no_creature_card_does_nothing(set_pool):
    """An empty record arms nothing: a delayed ability about no object would
    otherwise answer to the first permanent the event names, which is the
    widening every bound payload in this engine exists to prevent."""
    game = _w1g2_grave_duel(set_pool, ["Kaervek's Torch"])
    game.cast_from_hand(0, "Shallow Grave")
    game.resolve_stack()

    assert game.players[0].battlefield == [], game.log
    assert not [e for e in game.delayed_triggers if e.event == "next_end_step"], game.log


# --- W2G5: a combat record that outlives the combat (CR 508.1a) ---
#
# Jabari's Influence prints two things the engine had no channel for and one it
# had already written down and never reached.
#
# "that attacked you this turn" is the *past tense* of `attacking_you`, and the
# distinction is the card: `Permanent.defending_player_index` is the live combat
# relation and end of combat clears it, while this spell may only be cast **after
# combat** — so the live reading is always None by the time the question is
# asked. The declaration now stamps whom each attacker was declared against.
#
# And "…**and** put a -1/-0 counter on it" is `pronouns._parse_pronoun_counter_
# rider` — whose docstring names this very card — reached one punctuation mark
# too late: a conjunction is joined inside `parse_statement` and no rider table
# is consulted, so the same clause after a full stop put the counter on the
# target and after "and" put it on the ability's own source. On a spell that is
# no permanent at all, so the counter simply vanished. Neither raises.

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card


def _w2g5_jabari_board(set_pool):
    """Seat 1 attacks seat 0 with one of its two creatures, then combat ends.

    The phase is moved to the postcombat main directly rather than walked,
    because what this needs is the *state* the card is cast in: combat over,
    the live attack relation cleared, the turn's record still standing.
    """
    pool = set_pool("MIR")
    raider = Permanent(card=_mk_card("Raider", "Creature - Human", ""))
    homebody = Permanent(card=_mk_card("Homebody", "Creature - Human", ""))
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Jabari's Influence"]]),
        PlayerState(name="P2", battlefield=[raider, homebody]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0])[0]
    game.current_turn_phase = "postcombat_main"
    game.current_step = "postcombat_main"
    return game, raider, homebody


def test_jabaris_influence_is_supported(set_pool):
    program = compile_card_oracle(set_pool("MIR")["Jabari's Influence"])
    assert program.supported, program.reason


def test_jabaris_influence_takes_the_creature_that_attacked_you(set_pool):
    """Both halves in one game: the control change (CR 613 layer 2) and the
    counter that follows it. The counter is the half that was silent — it lands
    on the creature the first clause took, not on the spell."""
    game, raider, _homebody = _w2g5_jabari_board(set_pool)

    cast = game.cast_from_hand(
        0, "Jabari's Influence", target_player_index=1, target_permanent_index=0
    )
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert game.controller_index_of(raider) == 0, game.log
    assert (raider.effective_power, raider.effective_toughness) == (1, 2), game.log


def test_the_creature_that_stayed_home_is_not_a_legal_target(set_pool):
    """The narrowing is the card. Offered without it, Jabari's Influence is an
    unconditional Ritual of the Machine for one mana more."""
    game, _raider, _homebody = _w2g5_jabari_board(set_pool)

    cast = game.cast_from_hand(
        0, "Jabari's Influence", target_player_index=1, target_permanent_index=1
    )

    assert not cast.supported
    assert "no valid target" in cast.details


def test_the_conjoined_counter_lands_on_the_target(set_pool):
    """The rebinding, read off the compiled program: joined by "and", the
    pronoun used to reach the lowering as the ability's own source and produce
    ``add_counter_to_self`` — which on a spell places nothing at all while the
    card reports supported."""
    joined = compile_line("Gain control of target creature and put a -1/-0 counter on it.")
    stopped = compile_line("Gain control of target creature. Put a -1/-0 counter on it.")

    assert [i.kind for i in joined.instructions] == [i.kind for i in stopped.instructions]
    assert joined.instructions[1].kind == "add_counter_to_target"


def test_a_pronoun_after_an_untargeted_clause_is_not_rebound(set_pool):
    """The other direction. ``statement_bound_target`` offers only a spec the
    sentence *targeted* (CR 601.2c), so "Sacrifice a creature and put a +1/+1
    counter on it" keeps the reading it had — the rebinding must not invent a
    referent for a clause that chose nothing."""
    compiled = compile_line("Sacrifice a creature and put a +1/+1 counter on it.")

    assert compiled.instructions[1].kind == "add_counter_to_self"


# --- W2G5 (continued): "becomes blocked" (CR 509.1h) ---
#
# `picker_sweep --set MIR` had flagged Dazzling Beauty since the ingest, and
# W1G5 found why: the card was "supported" on its cantrip line alone, and its
# main sentence produced no instruction at all. It resolved, drew its card next
# upkeep, and let the attacker through.
#
# CR 509.1h is the rule that makes this cheap: a creature can be blocked by *no*
# creatures — it is the state an attacker is left in when its blockers leave
# combat — so nothing goes into any block map. The consequence falls out of a
# branch the combat damage step has had since it was written: an attacker that
# is blocked and has no blockers assigns its damage to nothing unless it has
# trample.


def _w2g5_beauty_combat(set_pool, *, cast: bool, trample: bool = False):
    """Seat 0 attacks with one creature; seat 1 may answer in declare blockers.

    The attacker is not blocked by anything either way, so the only difference
    between the two arms is the spell.
    """
    pool = set_pool("MIR")
    text = "Trample" if trample else ""
    bear = Permanent(card=_mk_card("Bear", "{2}{G}", "Creature - Bear", text))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bear]),
        PlayerState(name="P2", hand=[pool["Dazzling Beauty"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    result = None
    if cast:
        result = game.cast_from_hand(
            1, "Dazzling Beauty", target_player_index=0, target_permanent_index=0
        )
        game.resolve_stack()
    game.declare_blockers(1, {})
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game, bear, result


def test_dazzling_beauty_stops_the_attacker(set_pool):
    """The card, in a game. The control arm is what makes it a test: an
    instruction-less spell resolves just as quietly as a working one, and the
    only thing that tells them apart is the life total."""
    through, _bear, _ = _w2g5_beauty_combat(set_pool, cast=False)
    assert through.players[1].life == 18, through.log

    stopped, _bear, cast = _w2g5_beauty_combat(set_pool, cast=True)
    assert cast.supported, cast.details
    assert stopped.players[1].life == 20, stopped.log


def test_a_blocked_creature_with_trample_still_gets_through(set_pool):
    """CR 509.1h leaves a blocked creature blocked by nothing, and CR 702.19b
    lets trample assign the excess to the player — all of it, since there are no
    blockers to assign lethal to. The card is a fog for one creature, not a
    removal spell, and this is the edge that says so."""
    game, _bear, cast = _w2g5_beauty_combat(set_pool, cast=True, trample=True)

    assert cast.supported, cast.details
    assert game.players[1].life == 18, game.log


def test_the_mark_survives_the_combat_state_rebuild(set_pool):
    """The combat phase rebuilds ``blocked`` from the block maps on every prune,
    and a creature blocked by nobody is in none of them — so the flag alone
    would be undone by the next prune. Asserted directly, because the life total
    above would not tell a lost mark from a spell that never worked."""
    from engine.combat_assignment import BLOCKED_WITHOUT_BLOCKERS

    pool = set_pool("MIR")
    bear = Permanent(card=_mk_card("Bear", "{2}{G}", "Creature - Bear", ""))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bear]),
        PlayerState(name="P2", hand=[pool["Dazzling Beauty"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.cast_from_hand(
        1, "Dazzling Beauty", target_player_index=0, target_permanent_index=0
    ).supported
    game.resolve_stack()

    assert bear.metadata[BLOCKED_WITHOUT_BLOCKERS] is True
    game._prune_combat_state()
    assert bear.blocked, game.log


def test_a_creature_that_is_not_attacking_is_no_target(set_pool):
    """"Target **unblocked attacking** creature." Both adjectives are the card:
    without them this is a mark that can be put on anything, and the mark makes
    a creature that never attacked unable to deal combat damage.

    Asserted inside a real declare-blockers step with an attacker beside the
    idler, so the refusal is the *target description* and not the timing gate —
    which is a different sentence and would pass this test for the wrong reason.
    """
    pool = set_pool("MIR")
    raider = Permanent(card=_mk_card("Raider", "{1}{G}", "Creature - Bear", ""))
    idle = Permanent(card=_mk_card("Idler", "{1}{G}", "Creature - Bear", ""))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[raider, idle]),
        PlayerState(name="P2", hand=[pool["Dazzling Beauty"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    cast = game.cast_from_hand(
        1, "Dazzling Beauty", target_player_index=0, target_permanent_index=1
    )

    assert not cast.supported
    assert "no valid target" in cast.details, cast.details
    assert game.cast_from_hand(
        1, "Dazzling Beauty", target_player_index=0, target_permanent_index=0
    ).supported, "the control: the attacker beside it is a legal target"

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

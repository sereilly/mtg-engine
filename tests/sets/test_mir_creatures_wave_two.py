"""Per-card tests for Mirage's creatures — wave 2's sections.

The continuation of `test_mir_creatures.py`, which crossed the 2,600-line guard
at wave 2's integration with no single group at fault: three groups' blocks
merely summed. Cut at a **section boundary**, which is what
`tests/sets/README.md` asks for past the printed-type axis — every section here
is self-contained and written up in ROADMAP.md under the round or group that
bought it, so a section stays whole and stays findable from its round.

The same block convention holds: append a delimited block headed
``# --- W<wave>G<n>: <topic> ---`` with **its own imports at the top of its own
block**, and do not edit this docstring or an earlier block.
"""

from __future__ import annotations


# --- W2G3: Benevolent Unicorn, spell damage reduced by 1 ---
#
# A **replacement**, not a prevention shield, and the difference is the card:
# CR 120.8 makes a source that would deal 0 damage deal none at all, so a
# 1-damage spell reduced to 0 deals nothing, marks nothing and fires no "deals
# damage" trigger. Written as a shield it would have prevented 1 of 1 and still
# announced an event.

from engine import Game as _w2g3c_Game, PlayerState as _w2g3c_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w2g3c_load,  # noqa: E402
                                manifest_set_path as _w2g3c_path)
from engine.models import Permanent as _w2g3c_Permanent  # noqa: E402
from engine.replacements import (source_damage_reduction  # noqa: E402
                                 as _w2g3c_reduction)

from tests.helpers import _damage_dealt as _w2g3c_dealt  # noqa: E402


def _w2g3c_lea():
    return {card.name: card for card in _w2g3c_load(_w2g3c_path("LEA"))}


def _w2g3c_game(pool, hand=(), mine=(), theirs=()):
    lea = _w2g3c_lea()
    game = _w2g3c_Game(players=[
        _w2g3c_PlayerState(name="P1", hand=[lea[name] for name in hand],
                           battlefield=list(mine), library=[lea["Island"]] * 6),
        _w2g3c_PlayerState(name="P2", battlefield=list(theirs),
                           library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_w2g3_benevolent_unicorn_softens_a_burn_spell(set_pool):
    """"If a spell would deal damage to a permanent or player, it deals that
    much damage minus 1 to that permanent or player instead."

    Global: the sentence names no controller, so an opponent's Unicorn softens
    a spell aimed at its own controller exactly as it softens one aimed at
    anybody.
    """
    pool = set_pool("MIR")
    lea = _w2g3c_lea()
    game = _w2g3c_game(
        pool, hand=["Lightning Bolt"],
        mine=[_w2g3c_Permanent(card=pool["Benevolent Unicorn"])],
    )

    cast = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert game.players[1].life == 18, "3 damage minus 1"
    assert lea  # the fixture pool is what supplies the burn spell


def test_w2g3_two_unicorns_take_two_points(set_pool):
    """CR 616.1 would apply them one at a time in an order the affected player
    picks, and subtraction commutes — so the number is the same however they are
    ordered, which is why one candidate sums them rather than two candidates
    each taking a point."""
    pool = set_pool("MIR")
    game = _w2g3c_game(
        pool, hand=["Lightning Bolt"],
        mine=[_w2g3c_Permanent(card=pool["Benevolent Unicorn"]),
              _w2g3c_Permanent(card=pool["Benevolent Unicorn"])],
    )

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    game.resolve_stack()
    game._settle()

    assert game.players[1].life == 19


def test_w2g3_benevolent_unicorn_leaves_an_ability_alone(set_pool):
    """"A **spell**" is asked of the object whose instructions are running, not
    of the source's type line: a permanent's activated ability passes the
    permanent's own card as the source, and a type read would have to guess.
    Prodigal Sorcerer's ping is not a spell and takes its full point."""
    pool = set_pool("MIR")
    lea = _w2g3c_lea()
    game = _w2g3c_game(
        pool,
        mine=[_w2g3c_Permanent(card=pool["Benevolent Unicorn"]),
              _w2g3c_Permanent(card=lea["Prodigal Sorcerer"])],
    )
    game.players[0].battlefield[1].metadata["summoning_sickness_turn"] = -99

    used = game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_player_index=1, ability_index=0,
    )
    assert used.supported, used.details
    game.resolve_stack()
    game._settle()

    assert game.players[1].life == 19


def test_w2g3_benevolent_unicorn_leaves_combat_damage_alone(set_pool):
    """A creature is a permanent, never a spell — checked before the resolving
    object is asked for at all, so combat damage never reaches the list."""
    pool = set_pool("MIR")
    lea = _w2g3c_lea()
    attacker = _w2g3c_Permanent(card=lea["Hill Giant"])
    game = _w2g3c_game(
        pool, mine=[_w2g3c_Permanent(card=pool["Benevolent Unicorn"])],
        theirs=[attacker],
    )

    assert _w2g3c_dealt(
        game, game.players[0], 3, source=attacker, combat=True
    ) == 3


def test_w2g3_the_reduction_reads_its_own_sentence(set_pool):
    """The matcher's refusal test, which the positive cases cannot give: the
    two halves of the sentence have to name the **same** recipients, so a card
    reducing damage to a permanent and dealing the reduced amount to a creature
    is not this effect and stays unclaimed."""
    assert _w2g3c_reduction(
        "If a spell would deal damage to a permanent or player, it deals that "
        "much damage minus 1 to that permanent or player instead."
    ) == ("spell", 1)
    assert _w2g3c_reduction(
        "If a spell would deal damage to a permanent or player, it deals that "
        "much damage minus 1 to that creature or player instead."
    ) is None
    assert _w2g3c_reduction("Destroy target creature.") is None


# --- W2G4: an Aura reanimated onto the ability's own source ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.activation_restrictions import activation_denial


def _w2g4_hakim(set_pool, graveyard=(), attached=None):
    """Hakim on seat 0 with *graveyard* in his controller's pile.

    *attached* is an Aura card name already enchanting him, for the half of the
    ability's restriction that is about the board rather than about the step.
    """
    hakim = Permanent(card=set_pool("MIR")["Hakim, Loreweaver"])
    hakim.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[hakim],
            graveyard=[set_pool("MIR")[name] for name in graveyard],
            life=20,
        ),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    if attached is not None:
        from engine.auras import attach_aura

        aura = Permanent(card=set_pool("MIR")[attached])
        game.players[0].battlefield.append(aura)
        attach_aura(aura, hakim)
    game.start_turn(0)
    return game, hakim


def test_hakim_is_supported(set_pool):
    """Three lines, and two of them refused on the same defect: the lexer
    collapses a card's own name to a SELF token and the "attached to" reader
    listed only "it" and "that creature", so **any** card printing "attached to
    <its own name>" refused its whole line on unconsumed text."""
    program = compile_card_oracle(set_pool("MIR")["Hakim, Loreweaver"])
    assert program.supported, program.reason
    kinds = [ability.instruction.kind for ability in program.activated_abilities]
    assert kinds == ["reanimate_aura_onto_source", "destroy_all_matching"]


def test_hakim_returns_an_aura_from_the_graveyard_onto_himself(set_pool):
    """"{U}{U}: Return target Aura card from your graveyard to the battlefield
    attached to Hakim."

    CR 303.4f: the attachment is part of the *entry*, so the Aura has to arrive
    already on him — one that entered attached to nothing is what CR 704.5m
    puts straight back into the graveyard.
    """
    game, hakim = _w2g4_hakim(set_pool, graveyard=["Soar"])
    game.current_step = "upkeep"
    result = game.activate_permanent_ability(
        0, "Hakim, Loreweaver", permanent_index=0,
        ability_index=0, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert [c.name for c in game.players[0].graveyard] == [], game.log
    soar = [p for p in game.players[0].battlefield if p.card.name == "Soar"]
    assert len(soar) == 1, game.log
    assert soar[0].metadata.get("attached_to") is hakim, game.log
    assert [a.card.name for a in hakim.metadata.get("attached_auras")] == ["Soar"]


def test_hakim_leaves_an_aura_he_cannot_legally_enchant_in_the_graveyard(set_pool):
    """CR 303.4j: an attachment that would be illegal simply does not happen.

    Wellspring is an Aura card, so the picker offers it and the activation gate
    admits it — the refusal has to come at the move, from the same predicate
    every other attach path asks (``auras.aura_attach_refusal``): "Enchant
    **land**" is not a Wizard. Putting it onto the battlefield unattached would
    be strictly worse than not resolving, because the CR 704.5m sweep would bin
    it and the card would be gone from the game.
    """
    game, hakim = _w2g4_hakim(set_pool, graveyard=["Wellspring"])
    game.current_step = "upkeep"
    result = game.activate_permanent_ability(
        0, "Hakim, Loreweaver", permanent_index=0,
        ability_index=0, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert [c.name for c in game.players[0].graveyard] == ["Wellspring"], game.log
    assert [p.card.name for p in game.players[0].battlefield] == [
        "Hakim, Loreweaver"
    ], game.log


def test_hakim_destroys_only_the_auras_on_himself(set_pool):
    """"{U}{U}, {T}: Destroy all Auras attached to Hakim."

    The narrowing is the whole sentence. Read as a bare "all Auras" it is a
    board wipe, and the phrase parsed as a noun *filter* ("attached to a
    creature") is the same wipe wearing the card's words — so the assertion is
    that the opponent's Aura, on their own creature, survives.
    """
    game, hakim = _w2g4_hakim(set_pool, attached="Soar")
    theirs = Permanent(card=set_pool("MIR")["Zhalfirin Knight"])
    game.players[1].battlefield.append(theirs)
    from engine.auras import attach_aura

    their_aura = Permanent(card=set_pool("MIR")["Soar"])
    game.players[1].battlefield.append(their_aura)
    attach_aura(their_aura, theirs)

    result = game.activate_permanent_ability(
        0, "Hakim, Loreweaver", permanent_index=0, ability_index=1,
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert [p.card.name for p in game.players[0].battlefield] == [
        "Hakim, Loreweaver"
    ], game.log
    assert sorted(p.card.name for p in game.players[1].battlefield) == [
        "Soar", "Zhalfirin Knight",
    ], game.log


def test_hakim_may_not_reanimate_while_he_is_enchanted(set_pool):
    """"Activate only during your upkeep and **only if Hakim isn't enchanted**."

    A restriction is only done when something enforces it, and a card naming
    itself is the shape that silently was not: the row is written for "this
    <noun>" and the printed clause says "Hakim", so the clause matched nothing
    and the ability was usable every upkeep however many Auras he wore.
    """
    game, hakim = _w2g4_hakim(set_pool, graveyard=["Soar"], attached="Ward of Lights")
    game.current_step = "upkeep"
    line = compile_card_oracle(
        set_pool("MIR")["Hakim, Loreweaver"]
    ).activated_abilities[0].source_line

    assert activation_denial(game, 0, hakim, line) == "it is enchanted"
    result = game.activate_permanent_ability(
        0, "Hakim, Loreweaver", permanent_index=0,
        ability_index=0, target_permanent_index=0,
    )
    assert not result.supported, result.details
    assert [c.name for c in game.players[0].graveyard] == ["Soar"], game.log


def test_hakims_upkeep_clause_is_still_enforced_beside_it(set_pool):
    """The sentence conjoins two rules and both have to bite. The one that is
    *not* new is the one a fix to the other can quietly drop: `_conjuncts`
    splits on "and only", so a row written for the whole sentence would have
    read one rule and left the timing unenforced."""
    game, hakim = _w2g4_hakim(set_pool, graveyard=["Soar"])
    line = compile_card_oracle(
        set_pool("MIR")["Hakim, Loreweaver"]
    ).activated_abilities[0].source_line

    game.current_step = "precombat_main"
    assert activation_denial(game, 0, hakim, line) is not None
    game.current_step = "upkeep"
    assert activation_denial(game, 0, hakim, line) is None


# --- W2G4: a sacrifice priced by an aggregate rather than by a count ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w2g4_dreadnought(set_pool, others=(), interactive=True):
    """Phyrexian Dreadnought in seat 0's hand over a board of *others*."""
    perms = [Permanent(card=set_pool("MIR")[name]) for name in others]
    game = Game(players=[
        PlayerState(
            name="P1", hand=[set_pool("MIR")["Phyrexian Dreadnought"]],
            # A *copy*: the battlefield is a live list, and handing the same
            # object back would make `perms` grow by whatever enters — which is
            # the Dreadnought itself, one line below.
            battlefield=list(perms), life=20,
        ),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(0)
    game.queue_from_hand(0, "Phyrexian Dreadnought")
    game.resolve_stack()
    return game, perms


def test_phyrexian_dreadnought_is_supported(set_pool):
    """"…unless you sacrifice **any number of creatures with total power 12 or
    greater**."

    The threshold cannot be a count and cannot ride the filter: how many
    permanents satisfy it depends on which ones are chosen, and a filter is
    asked of one permanent at a time. A lowering that dropped it would have
    priced a twelve-power cost at one creature.
    """
    program = compile_card_oracle(set_pool("MIR")["Phyrexian Dreadnought"])
    assert program.supported, program.reason
    offer = program.triggered_abilities[0].instruction
    assert offer.kind == "may"
    action = offer.payload["action"][0]
    assert action.kind == "sacrifice_permanents_totalling"
    assert action.payload["characteristic"] == "power"
    assert action.payload["at_least"] == 12
    assert [step.kind for step in offer.payload["otherwise"]] == ["sacrifice_self"]


def test_phyrexian_dreadnought_refuses_a_set_that_falls_short(set_pool):
    """The floor is the whole of the price. An answer under it is not a cheaper
    payment, it is no payment — so the prompt stands rather than being consumed,
    and the creature it named is still on the battlefield."""
    game, perms = _w2g4_dreadnought(
        set_pool, others=["Crash of Rhinos", "Crimson Hellkite"]
    )
    assert game.confirm_optional_pay(0, accept=True), game.log
    assert [c.kind for c in game.pending_choices] == ["aggregate_sacrifice"]

    assert not game.confirm_aggregate_sacrifice(0, [perms[0].permanent_id])
    assert [c.kind for c in game.pending_choices] == ["aggregate_sacrifice"]
    assert perms[0] in game.players[0].battlefield, game.log


def test_phyrexian_dreadnought_accepts_a_set_that_clears_the_floor(set_pool):
    """An 8/4 and a 6/6 total 14, which pays — and only the two chosen go. The
    Dreadnought stays, which is the whole of what the cost buys."""
    game, perms = _w2g4_dreadnought(
        set_pool, others=["Crash of Rhinos", "Crimson Hellkite"]
    )
    game.confirm_optional_pay(0, accept=True)
    assert game.confirm_aggregate_sacrifice(
        0, [perm.permanent_id for perm in perms]
    ), game.log

    assert [p.card.name for p in game.players[0].battlefield] == [
        "Phyrexian Dreadnought"
    ], game.log
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Crash of Rhinos", "Crimson Hellkite",
    ], game.log


def test_phyrexian_dreadnought_totals_power_through_the_layers(set_pool):
    """CR 613: what a creature's power *is* now, not what its card prints. A
    2/2 pumped to 12/12 pays on its own, and a reader that took the printed
    number would refuse the set the rules allow."""
    game, perms = _w2g4_dreadnought(set_pool, others=["Femeref Knight"])
    from engine.pt import add_pt_modifier

    add_pt_modifier(perms[0], 10, 10)
    game.confirm_optional_pay(0, accept=True)
    assert perms[0].effective_power == 12
    assert game.confirm_aggregate_sacrifice(0, [perms[0].permanent_id]), game.log
    assert [p.card.name for p in game.players[0].battlefield] == [
        "Phyrexian Dreadnought"
    ], game.log


def test_phyrexian_dreadnought_may_be_sacrificed_to_its_own_trigger(set_pool):
    """Nothing in CR 701.17a excludes the ability's own source, and the printed
    phrase says "any number of creatures" rather than "another" — so the 12/12
    on the battlefield is a legal payment for its own cost. The offer is
    takeable even on an otherwise empty board because of it."""
    game, _ = _w2g4_dreadnought(set_pool)
    game.confirm_optional_pay(0, accept=True)
    choice = game.pending_choices[0]
    candidates = game.aggregate_sacrifice_candidates(
        0, dict(choice.data["_payload"])
    )
    assert [perm.card.name for perm in candidates] == ["Phyrexian Dreadnought"]

    assert game.confirm_aggregate_sacrifice(0, [candidates[0].permanent_id])
    assert game.players[0].battlefield == [], game.log


def test_phyrexian_dreadnought_goes_when_the_offer_is_declined(set_pool):
    """The decline is the card. "Sacrifice it" is what happens when the price
    is not paid, and it is the half a dropped threshold would have made
    unreachable."""
    game, perms = _w2g4_dreadnought(
        set_pool, others=["Crash of Rhinos", "Crimson Hellkite"]
    )
    assert game.confirm_optional_pay(0, accept=False), game.log

    assert [p.card.name for p in game.players[0].battlefield] == [
        "Crash of Rhinos", "Crimson Hellkite",
    ], game.log
    assert [c.name for c in game.players[0].graveyard] == [
        "Phyrexian Dreadnought"
    ], game.log


# --- W3G3: Tainted Specter, an offer whose refusal is what the card is for ---
#
# "Target player discards a card unless they put a card from their hand on top
# of their library. If that player discards a card this way, this creature
# deals 1 damage to each creature and each player."
#
# Three riders on one activated ability, and only the middle one is new. The
# "unless" is `ast.May` with the put-back as its *action*, the way every other
# non-mana toll in this grammar decomposes; the sweep behind it is a condition
# on the record the discard writes, folded into the offer's decline branch by
# `_lower_steps`; and "Activate only as a sorcery" was already a row in
# `engine/activation_restrictions.py`.
#
# The condition is the half a kind-shaped assertion cannot see. A player with an
# empty hand can neither put a card back nor discard one, so the offer is never
# made, the discard takes nothing and **the sweep must not happen** — which is
# what `it_happened` over `discarded_count` buys and what folding the damage
# into the decline branch unconditionally would have lost.

from engine import (Game as _w3g3c_Game,  # noqa: E402
                    PlayerState as _w3g3c_PlayerState)
from engine.card_loader import (load_cards as _w3g3c_load,  # noqa: E402
                                manifest_set_path as _w3g3c_path)
from engine.models import Permanent as _w3g3c_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g3c_compile  # noqa: E402


def _w3g3c_lea():
    return {card.name: card for card in _w3g3c_load(_w3g3c_path("LEA"))}


def _w3g3c_specter_game(set_pool, opponent_hand=2, theirs=("Grizzly Bears",)):
    """A Specter under P1 and a two-card hand under P2, ready to activate."""
    lea = _w3g3c_lea()
    specter = _w3g3c_Permanent(card=set_pool("MIR")["Tainted Specter"])
    specter.metadata["summoning_sickness_turn"] = -99
    game = _w3g3c_Game(players=[
        _w3g3c_PlayerState(name="P1", battlefield=[specter],
                           library=[lea["Island"]] * 8),
        _w3g3c_PlayerState(
            name="P2", hand=[lea["Island"]] * opponent_hand,
            battlefield=[_w3g3c_Permanent(card=lea[name]) for name in theirs],
            library=[lea["Forest"]] * 8,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}
    game.start_turn(0)
    return game, specter


def test_w3g3_tainted_specter_is_supported(set_pool):
    """The offer, its penalty and the conditional sweep, in that shape.

    The sweep sits **inside** the decline branch rather than beside it: it can
    only happen when the put-back did not, and `_lower_steps` folds a step that
    reads what a branch records into that branch.
    """
    program = _w3g3c_compile(set_pool("MIR")["Tainted Specter"])
    assert program.supported, program.reason

    ability = program.activated_abilities[0]
    assert ability.cost.requires_tap
    assert ability.cost.mana["B"] == 2 and ability.cost.mana["generic"] == 1
    offer = ability.instruction
    assert offer.kind == "may" and offer.payload["actor"] == "that_player"
    assert [step.kind for step in offer.payload["action"]] == [
        "put_hand_cards_on_library"
    ]
    declined = offer.payload["otherwise"]
    assert [step.kind for step in declined] == ["discard_target_cards", "if_then"]
    assert declined[1].payload["condition"] == {
        "kind": "it_happened", "key": "discarded_count",
    }


def test_w3g3_tainted_specter_taking_the_offer_deals_no_damage(set_pool):
    """Accepting puts a card on the library and stops there. Nothing is
    discarded, so the sentence behind the offer has nothing to fire on."""
    game, _ = _w3g3c_specter_game(set_pool)
    game.activate_permanent_ability(0, "Tainted Specter", target_player_index=1)
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]

    assert game.confirm_optional_pay(1, accept=True), game.log
    assert [c.kind for c in game.pending_choices] == ["hand_to_library"]
    assert game.confirm_hand_to_library(1, [0]), game.log

    assert len(game.players[1].hand) == 1
    assert game.players[1].library[0].name == "Island"
    assert game.players[1].graveyard == []
    assert [player.life for player in game.players] == [20, 20], game.log
    assert game.players[1].battlefield[0].damage_marked == 0


def test_w3g3_tainted_specter_declining_discards_and_then_sweeps(set_pool):
    """Declining is what the card is for: the discard happens and the sweep
    behind it deals 1 to **each** creature and **each** player — the Specter
    and its own controller included."""
    game, specter = _w3g3c_specter_game(set_pool)
    game.activate_permanent_ability(0, "Tainted Specter", target_player_index=1)

    assert game.confirm_optional_pay(1, accept=False), game.log
    assert [c.kind for c in game.pending_choices] == ["discard"]
    assert game.confirm_discard(1, [0]), game.log

    assert [c.name for c in game.players[1].graveyard] == ["Island"]
    assert [player.life for player in game.players] == [19, 19], game.log
    assert specter.damage_marked == 1
    assert game.players[1].battlefield[0].damage_marked == 1


def test_w3g3_tainted_specter_sweeps_nothing_off_an_empty_hand(set_pool):
    """The condition, and the whole reason it is one. With no cards there is no
    offer to make and no card to discard, so "discards a card this way" is
    false — folded unconditionally into the decline branch the sweep would have
    fired for a player who lost nothing."""
    game, specter = _w3g3c_specter_game(set_pool, opponent_hand=0)
    game.activate_permanent_ability(0, "Tainted Specter", target_player_index=1)

    assert game.pending_choices == [], game.log
    assert [player.life for player in game.players] == [20, 20], game.log
    assert specter.damage_marked == 0
    assert game.players[1].battlefield[0].damage_marked == 0


def test_w3g3_tainted_specter_is_sorcery_speed(set_pool):
    """CR 602.5's printed clause, enforced rather than parsed and dropped. The
    failure this guards is not a crash: it is an ability usable on an
    opponent's turn, which is silent and in its controller's favour."""
    game, _ = _w3g3c_specter_game(set_pool)
    game.start_turn(1)

    result = game.activate_permanent_ability(
        0, "Tainted Specter", target_player_index=1
    )
    assert not result.supported
    assert "sorcery-speed" in result.details
    assert game.pending_choices == [], game.log
    assert len(game.players[1].hand) == 2

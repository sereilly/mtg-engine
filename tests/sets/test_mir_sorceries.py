"""Per-card tests for Mirage's sorceries.

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


# --- Round 6: narrowings the sweep and the tuck were dropping ---

from engine import Game, PlayerState
from engine.models import Permanent


def _r6_cast(set_pool, spell: str, own=(), theirs=()):
    pool = set_pool("MIR")
    mine = [Permanent(card=pool[name]) for name in own]
    yours = [Permanent(card=pool[name]) for name in theirs]
    game = Game(players=[
        PlayerState(name="P1", battlefield=mine, hand=[pool[spell]],
                    library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=yours, library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(0, spell)
    assert result.supported, result.details
    game.resolve_stack()
    return game, mine, yours


def test_blinding_light_taps_only_the_nonwhite(set_pool):
    """"Tap all **nonwhite** creatures."

    The sweep already resolves through ``subject_matches``, which tests
    ``exclude_colors`` like any other key — the whitelist in the lowering was
    the only thing refusing the word. Dropping it instead would have tapped the
    caster's own white team, which is the direction a dropped narrowing on a
    sweep always goes.
    """
    game, mine, yours = _r6_cast(
        set_pool, "Blinding Light",
        own=["Femeref Knight"],            # white
        theirs=["Cadaverous Knight"],      # black
    )

    assert not mine[0].tapped
    assert yours[0].tapped


def test_fallow_earth_tucks_a_land(set_pool):
    """"Put target land on top of its owner's library." The other card the
    creature-pinned tuck refused."""
    pool = set_pool("MIR")
    land = Permanent(card=pool["Island"])
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Fallow Earth"]], library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=[land], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(
        0, "Fallow Earth", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert not game.is_on_battlefield(land)
    assert game.players[1].library[0].name == "Island"


# --- W1G4: the zones / cards / library family ---

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent


def test_polymorph_reanimates_off_the_victims_own_library(set_pool):
    """"Destroy target creature. It can't be regenerated. **Its controller**
    reveals cards from the top of their library until they reveal a creature
    card. The player puts that card onto the battlefield, then shuffles all
    other cards revealed this way into their library."

    Transmogrify's procedure behind a destroy instead of an exile, and three
    words apart from it: "its controller" for "that creature's controller",
    "the player" for "that player", and "all other cards revealed this way" for
    "the rest". None of the three changes what the card does, so they are
    alternatives inside the one rider rather than a second production.

    The creature arrives on the *victim's* battlefield, out of the *victim's*
    library -- the seat the destroy recorded, not the caster.
    """
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[pool["Polymorph"]],
                         library=[pool["Island"]] * 5),
        _W1G4PlayerState(
            name="P2", battlefield=[_W1G4Permanent(card=pool["Femeref Scouts"])],
            library=[pool["Island"], pool["Mountain"], pool["Viashino Warrior"],
                     pool["Plains"]],
        ),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.cast_from_hand(
        0, "Polymorph", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert [c.name for c in game.players[1].graveyard] == ["Femeref Scouts"]
    assert [p.card.name for p in game.players[1].battlefield] == ["Viashino Warrior"]
    assert game.players[0].battlefield == [], "the caster reanimates nothing"
    assert sorted(c.name for c in game.players[1].library) == [
        "Island", "Mountain", "Plains",
    ], "the cards revealed on the way are shuffled back, not milled"
    assert game.players[1].graveyard == [
        card for card in game.players[1].graveyard if card.name == "Femeref Scouts"
    ], "nothing revealed reached a graveyard"


def _w1g4_look_board(set_pool, spell, *, library, seat1_hand=(), interactive=(0,)):
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[pool[spell]],
                         library=[pool[n] for n in library]),
        _W1G4PlayerState(name="P2", hand=[pool[n] for n in seat1_hand],
                         library=[pool["Mountain"]] * 4),
    ])
    game.interactive_seats = set(interactive)
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, pool


_W1G4_SEVEN = (
    "Femeref Scouts", "Viashino Warrior", "Mana Prism", "Fire Diamond",
    "Island", "Mountain", "Plains", "Swamp", "Forest",
)


def test_ancestral_memories_takes_two_and_bins_the_other_five(set_pool):
    """"Look at the top seven cards of your library. Put **two** of them into
    your hand and the rest into your graveyard."

    Two firsts for this template: a pick count other than one -- the word "one"
    was a literal in the production, so the only card in the pool that takes two
    refused on the number it printed -- and "the rest **into your graveyard**"
    as a destination for the whole remainder, where Waker of Waves prints that
    fate for a single named card.

    The two picks are a *chain* of one-card prompts, because taking a card
    renumbers the pile behind it. The assertions are about counts as much as
    names: seven leave the library, two reach the hand, five reach the
    graveyard, and the spell itself resolves only once the last prompt is
    answered (CR 608.2).
    """
    game, _ = _w1g4_look_board(set_pool, "Ancestral Memories", library=_W1G4_SEVEN)

    assert game.cast_from_hand(0, "Ancestral Memories").supported
    assert game.waiting_prompt() is not None, "the resolution waits (CR 117.3b)"

    assert game.confirm_look_top_pick(0, 2), "Mana Prism"
    assert [c.name for c in game.players[0].hand] == ["Mana Prism"]
    assert game.waiting_prompt() is not None, "one pick still owed"

    assert game.confirm_look_top_pick(0, 0), "Femeref Scouts, after the renumber"

    assert [c.name for c in game.players[0].hand] == ["Mana Prism", "Femeref Scouts"]
    assert [c.name for c in game.players[0].graveyard] == [
        "Viashino Warrior", "Fire Diamond", "Island", "Mountain", "Plains",
        "Ancestral Memories",
    ], "five looked-at cards, then the spell itself"
    assert [c.name for c in game.players[0].library] == ["Swamp", "Forest"]
    assert game.pending_choices == []


def test_ancestral_memories_drains_both_picks_for_a_non_interactive_seat(set_pool):
    """The AI path takes the same two cards through the same chain -- a default
    that answered once would leave the second prompt queued and the spell
    resolving forever."""
    game, _ = _w1g4_look_board(
        set_pool, "Ancestral Memories", library=_W1G4_SEVEN, interactive=()
    )

    game.cast_from_hand(0, "Ancestral Memories")
    game.auto_resolve_pending_choices()

    assert len(game.players[0].hand) == 2
    assert len(game.players[0].library) == 2
    assert game.pending_choices == []


def test_painful_memories_tucks_the_chosen_card_and_takes_only_one_copy(set_pool):
    """"Look at target opponent's hand and choose a card from it. Put that card
    on top of that player's library."

    Mind Warp's template with the other printed ending, so ``fate`` grows a
    third value rather than the family a second node. The count assertion is
    the one that matters here: a hand repeats the *same* ``CardDefinition``
    object for every copy, so a removal spelled as an identity filter takes all
    of them -- the tuck goes through ``take_card_from_hand`` and moves exactly
    one.
    """
    game, pool = _w1g4_look_board(
        set_pool, "Painful Memories", library=("Island",) * 5,
        seat1_hand=("Island", "Mana Prism", "Island"),
    )

    assert game.cast_from_hand(0, "Painful Memories", target_player_index=1).supported
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=0)

    assert [c.name for c in game.players[1].hand] == ["Mana Prism", "Island"], (
        "one Island moved, not both"
    )
    assert game.players[1].library[0].name == "Island"
    assert len(game.players[1].library) == 5
    assert game.players[1].graveyard == [], "a tuck is not a discard"


def test_sealed_fate_looks_through_the_opponents_library_and_the_caster_decides(set_pool):
    """"Look at the top X cards of **target opponent's** library. Exile one of
    those cards and put the rest back on top of that player's library in any
    order."

    The look-and-pick template over somebody else's pile, which is the one shape
    ``looker`` could not say: that field answers "who looks" and "whose library"
    with one word, because Ashnod's Cylix prints "target player looks at the top
    three cards of **their** library". Here the two come apart -- the cards are
    the opponent's and every decision about them is the caster's -- so
    ``pile_owner`` is its own field and one reader
    (``Game.look_top_pile_index``) answers it for the offer, the resolution and
    the client alike.

    Two more firsts ride along: X as the count, and ``exile`` as a destination
    for the taken card. The exiled card goes to its **owner's** exile
    (CR 400.3), and the reorder that follows is answered by the caster over the
    opponent's library.
    """
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[pool["Sealed Fate"]],
                         library=[pool["Plains"]] * 4),
        _W1G4PlayerState(name="P2", library=[
            pool["Femeref Scouts"], pool["Mana Prism"], pool["Viashino Warrior"],
            pool["Island"], pool["Mountain"],
        ]),
    ])
    game.interactive_seats = {0}
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.cast_from_hand(
        0, "Sealed Fate", target_player_index=1, x_value=3
    ).supported
    prompt = game.pending_choices[0]
    assert prompt.player_index == 0, "the caster answers"
    assert game.look_top_pile_index(prompt) == 1, "the opponent's library is read"
    assert game.live_look_top_candidates(prompt) == [0, 1, 2]

    assert game.confirm_look_top_pick(0, 1)

    assert [c.name for c in game.players[1].exile] == ["Mana Prism"]
    assert game.players[0].exile == [], "CR 400.3: its owner's exile"
    assert [c.name for c in game.players[1].library] == [
        "Femeref Scouts", "Viashino Warrior", "Island", "Mountain",
    ], "the rest go back on top, not to a graveyard"
    assert game.players[0].library == [pool["Plains"]] * 4, (
        "the caster's own library is untouched"
    )

    reorder = game.pending_choices[0]
    assert (reorder.kind, reorder.player_index) == ("reorder_library", 0)
    assert reorder.data["target_index"] == 1
    assert game.resolve_pending_choice(
        "reorder_library", 0, new_order=[1, 0], shuffle=False
    )
    assert [c.name for c in game.players[1].library][:2] == [
        "Viashino Warrior", "Femeref Scouts",
    ]


def test_dream_cache_sends_both_cards_to_the_end_the_player_names(set_pool):
    """"Draw three cards, then put two cards from your hand **both on top of
    your library or both on the bottom of your library**."

    Brainstorm's prompt with the end printed as a choice, which is the only
    thing that differs -- same cards, same hand, same prompt -- so it is a
    field on the node rather than a second production. The repeated "both" is
    read as one phrase: a sentence letting the two cards go to different ends
    is a card nobody printed.

    The order is the other half of the reading. On top the first card named
    ends up on top, so the cards are laid down in reverse; on the bottom the
    first named goes down first. Both are the same sentence read from the
    library's own end.
    """
    pool = set_pool("MIR")
    library = [pool[n] for n in (
        "Femeref Scouts", "Mana Prism", "Viashino Warrior",
        "Island", "Mountain", "Plains",
    )]

    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[pool["Dream Cache"]], library=list(library)),
        _W1G4PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = {0}
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.cast_from_hand(0, "Dream Cache").supported
    assert [c.name for c in game.players[0].hand] == [
        "Femeref Scouts", "Mana Prism", "Viashino Warrior",
    ]
    assert game.confirm_hand_to_library(0, [0, 1], to_bottom=True)

    assert [c.name for c in game.players[0].hand] == ["Viashino Warrior"]
    assert [c.name for c in game.players[0].library] == [
        "Island", "Mountain", "Plains", "Femeref Scouts", "Mana Prism",
    ]

    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[pool["Dream Cache"]], library=list(library)),
        _W1G4PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = {0}
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.cast_from_hand(0, "Dream Cache")

    assert game.confirm_hand_to_library(0, [1, 0])
    assert [c.name for c in game.players[0].library][:2] == [
        "Mana Prism", "Femeref Scouts",
    ], "the first named ends up on top"


def test_a_card_that_names_no_end_refuses_a_bottoming_answer(set_pool, catalog_by_name):
    """Brainstorm puts its two cards on **top**, and a client saying otherwise
    is refused rather than ignored.

    Ignoring it is the failure that matters: the cards would go on top while
    the client believed it had bottomed them, which is a silently different
    spell. The key the resolver checks is the same one the renderer reads to
    decide whether to offer the second button at all.
    """
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[catalog_by_name["Brainstorm"]],
                         library=[pool["Island"]] * 6),
        _W1G4PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = {0}
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.cast_from_hand(0, "Brainstorm").supported
    assert not game.confirm_hand_to_library(0, [0, 1], to_bottom=True)
    assert game.confirm_hand_to_library(0, [0, 1])


# --- W1G3: damage / prevention / life ---

from engine import Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent


def _w1g3_cast(set_pool, spell, own=(), theirs=(), **kwargs):
    """Cast *spell* from seat 0 with the named permanents on each battlefield."""
    pool = set_pool("MIR")
    mine = [_W1G3Permanent(card=pool[name]) for name in own]
    yours = [_W1G3Permanent(card=pool[name]) for name in theirs]
    game = Game(players=[
        _W1G3PlayerState(name="P1", battlefield=mine, hand=[pool[spell]],
                         library=[pool["Island"]] * 5),
        _W1G3PlayerState(name="P2", battlefield=yours,
                         library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(0, spell, **kwargs)
    assert result.supported, result.details
    game.resolve_stack()
    return game, mine, yours


def test_kaerveks_hex_deals_the_additional_point_only_to_green(set_pool):
    """"deals 1 damage to each nonblack creature **and an additional 1 damage
    to each green creature**."

    The rider is a second damage clause, so a green nonblack creature takes
    both points and a green creature is not exempted from the first. The black
    creature takes neither, which is what makes this a test of the *first*
    clause's narrowing as well: a reader that dropped "nonblack" would kill it.
    """
    game, mine, yours = _w1g3_cast(
        set_pool, "Kaervek's Hex",
        own=["Zhalfirin Commander"],       # white, 2/2 — first clause only
        theirs=["Cadaverous Knight",       # black — neither clause
                "Wild Elephant"],          # green 3/3 — both clauses
    )

    assert mine[0].damage_marked == 1
    assert yours[0].damage_marked == 0
    assert yours[1].damage_marked == 2


def test_tropical_storm_reads_the_other_printed_word_order(set_pool):
    """"deals X damage to each creature with flying **and 1 additional damage
    to each blue creature**."

    The same rider with "additional" printed after the number instead of before
    it. Both spellings reach one production: a blue flier takes X+1, a blue
    ground creature takes only the 1, and a non-blue ground creature takes
    nothing at all — the third is what proves the first clause kept its
    ``with_keywords`` narrowing rather than becoming a board sweep.
    """
    game, mine, yours = _w1g3_cast(
        set_pool, "Tropical Storm",
        own=["Zhalfirin Commander"],       # white, no flying — neither clause
        theirs=["Wall of Corpses",         # black, no flying — neither
                "Azimaet Drake"],          # blue 1/3 flier — both clauses
        x_value=1,
    )

    assert mine[0].damage_marked == 0
    assert yours[0].damage_marked == 0
    assert yours[1].damage_marked == 2


def test_reign_of_chaos_asks_for_a_land_by_its_printed_subtype(set_pool):
    """"Destroy target **Plains** and target white creature."

    Two independent target roles, which the picker has read since Fumarole —
    the only thing refusing this card was the *name* of the first slot, because
    "Plains" is a subtype and the role namer read card types alone. The land is
    destroyed by the slot that names it and the untargeted Island is not, which
    is what proves the slot kept its filter rather than becoming "any land".
    """
    pool = set_pool("MIR")
    plains = _W1G3Permanent(card=pool["Plains"])
    island = _W1G3Permanent(card=pool["Island"])
    knight = _W1G3Permanent(card=pool["Zhalfirin Commander"])   # white
    zombie = _W1G3Permanent(card=pool["Cadaverous Knight"])     # black
    game = Game(players=[
        _W1G3PlayerState(name="P1", hand=[pool["Reign of Chaos"]],
                         library=[pool["Island"]] * 5),
        _W1G3PlayerState(name="P2", battlefield=[plains, island, knight, zombie],
                         library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    result = game.cast_from_hand(
        0, "Reign of Chaos", mode_index=0,
        target_permanent_ids=[plains.permanent_id, knight.permanent_id],
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert not game.is_on_battlefield(plains)
    assert not game.is_on_battlefield(knight)
    assert game.is_on_battlefield(island)
    assert game.is_on_battlefield(zombie)


# --- W1G5: the statics / characteristics / control family ---

from engine import Game, PlayerState
from engine.models import Permanent


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


def test_choking_sands_damages_only_over_a_nonbasic_land(set_pool):
    """"Destroy target non-Swamp land. **If that land was nonbasic**, this spell
    deals 2 damage to the land's controller."

    Both halves already worked apart. What refused was the condition's printed
    shape: Icequake's "if that land was **a snow land**" spells the head noun
    out and this one leaves it off, because the sentence supplied it two words
    earlier. The adjective run is lifted out, the noun put back, and the result
    handed to the same noun parser — so "nonbasic" is the same restriction here
    as in any target's description.
    """
    pool = set_pool("MIR")
    game = _g5_game(
        pool, ["Choking Sands"],
        opponent=[Permanent(card=pool["Bad River"]), Permanent(card=pool["Forest"])],
    )
    river = game.players[1].battlefield[0]

    cast = game.cast_from_hand(0, "Choking Sands", target_player_index=1,
                               target_permanent_index=0)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(river)
    assert game.players[1].life == 18, "a nonbasic land takes the 2 damage"


def test_choking_sands_spares_a_basic_lands_controller(set_pool):
    """The other arm of the same condition. Dropping it would have made the
    damage unconditional, which is a strictly better card than the printed
    one."""
    pool = set_pool("MIR")
    game = _g5_game(
        pool, ["Choking Sands"],
        opponent=[Permanent(card=pool["Forest"])],
    )
    forest = game.players[1].battlefield[0]

    cast = game.cast_from_hand(0, "Choking Sands", target_player_index=1,
                               target_permanent_index=0)
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(forest)
    assert game.players[1].life == 20


# --- W2G3: the destroy family's back-references ---
#
# Three sorceries whose second sentence asks a question about what their first
# one destroyed, and three different questions: how many died (Reign of Terror),
# whose each of them was, counted per seat (Builder's Bane), and whose each of
# them was, one at a time (Seeds of Innocence).

from engine import Game as _w2g3_Game, PlayerState as _w2g3_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w2g3_load,  # noqa: E402
                                manifest_set_path as _w2g3_path)
from engine.models import Permanent as _w2g3_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w2g3_compile  # noqa: E402


def _w2g3_lea():
    return {card.name: card for card in _w2g3_load(_w2g3_path("LEA"))}


def _w2g3_game(pool, hand, mine=(), theirs=()):
    """One spell in hand and two boards, with nobody interactive.

    A non-interactive seat answers a `mode_choice` prompt with the first
    printed mode the moment it is armed, which is what makes Reign of Terror's
    "destroy all green creatures **or** all white creatures" testable without a
    client — and what makes the mode it takes the green half.
    """
    lea = _w2g3_lea()
    game = _w2g3_Game(players=[
        _w2g3_PlayerState(name="P1", hand=[pool[name] for name in hand],
                          battlefield=list(mine),
                          library=[lea["Island"]] * 6),
        _w2g3_PlayerState(name="P2", battlefield=list(theirs),
                          library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_w2g3_reign_of_terror_takes_one_colour_and_charges_for_each_death(set_pool):
    """"Destroy all green creatures or all white creatures. They can't be
    regenerated. You lose 2 life for each creature that died this way."

    Both halves of the sentence were missing and each was invisible to the
    other. The rider is printed with the pronoun "they" after a *modal* destroy,
    which the fold reached only in its noun spelling; and the life loss is the
    trailing "for each", which the loss production read over a bare noun phrase
    and so stopped in front of the relative clause.
    """
    pool = set_pool("MIR")
    lea = _w2g3_lea()
    game = _w2g3_game(
        pool, ["Reign of Terror"],
        mine=[_w2g3_Permanent(card=lea["Grizzly Bears"]),
              _w2g3_Permanent(card=lea["Savannah Lions"])],
        theirs=[_w2g3_Permanent(card=lea["Grizzly Bears"]),
                _w2g3_Permanent(card=lea["Mons's Goblin Raiders"])],
    )

    cast = game.cast_from_hand(0, "Reign of Terror")
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert [p.card.name for p in game.players[0].battlefield] == ["Savannah Lions"]
    assert [p.card.name for p in game.players[1].battlefield] == [
        "Mons's Goblin Raiders"
    ]
    assert game.players[0].life == 16, "2 life for each of the two green deaths"
    assert game.players[1].life == 20, "the loss is the caster's, not everyone's"


def test_w2g3_reign_of_terror_beats_a_regeneration_shield(set_pool):
    """The rider is the half a modal destroy was dropping, so it gets a game of
    its own: a shielded creature that survived would also be a creature the life
    loss never counted, and both halves would be wrong in the same direction."""
    pool = set_pool("MIR")
    lea = _w2g3_lea()
    game = _w2g3_game(
        pool, ["Reign of Terror"],
        theirs=[_w2g3_Permanent(card=lea["Grizzly Bears"])],
    )
    bear = game.players[1].battlefield[0]
    bear.regeneration_shield = 1

    game.cast_from_hand(0, "Reign of Terror")
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(bear), "CR 701.15c: the shield is ignored"
    assert game.players[0].life == 18


def test_w2g3_a_life_loss_counts_only_what_this_effect_destroyed(set_pool):
    """"This way" is not "this turn", and the refusal says so. With no destroy
    in front of it the clause names nothing, and lowering it anyway would have
    read an absent record as a zero — a card that reports supported and loses
    the caster no life at all."""
    from engine.grammar import compile_line as _compile

    alone = _compile("You lose 2 life for each creature that died this way.")
    assert alone.parsed, "the trailing clause parses"
    assert alone.lowering_error == (
        "back-reference to 'destroyed_this_way' with no producer in this effect"
    )

    turn = _compile("You lose 2 life for each creature that died this turn.")
    assert turn.parsed, "the sibling spelling parses through the same reader"
    assert turn.lowering_error == (
        "no life-loss handler counts the turn's death tally"
    ), "read but refused, rather than silently counted as the other window"


def test_w2g3_builders_bane_charges_each_player_for_their_own_losses(set_pool):
    """"Destroy X target artifacts. Builder's Bane deals damage to each player
    equal to the number of artifacts **they controlled** that were put into a
    graveyard this way."

    The possessive is the whole card. Dropped, both seats take the total — three
    artifacts destroyed and both players take 3 — which is a spell that reports
    supported and hits about twice as hard as it prints.
    """
    pool = set_pool("MIR")
    lea = _w2g3_lea()
    game = _w2g3_game(
        pool, ["Builder's Bane"],
        mine=[_w2g3_Permanent(card=lea["Mox Pearl"])],
        theirs=[_w2g3_Permanent(card=lea["Icy Manipulator"]),
                _w2g3_Permanent(card=lea["Jade Statue"])],
    )
    ids = [
        game.players[0].battlefield[0].permanent_id,
        game.players[1].battlefield[0].permanent_id,
        game.players[1].battlefield[1].permanent_id,
    ]

    cast = game.cast_from_hand(
        0, "Builder's Bane", x_value=3, target_permanent_ids=ids,
    )
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.players[0].battlefield
    assert not game.players[1].battlefield
    assert game.players[0].life == 19, "one artifact of the caster's"
    assert game.players[1].life == 18, "two of the opponent's"


def test_w2g3_builders_bane_counts_only_what_it_destroyed(set_pool):
    """An artifact nobody targeted is nobody's loss. The per-seat tally is read
    off the seat map the destroy froze rather than off a board scan, so a
    survivor cannot be counted — and a seat that lost nothing takes nothing,
    which CR 120.8 makes no damage event at all."""
    pool = set_pool("MIR")
    lea = _w2g3_lea()
    game = _w2g3_game(
        pool, ["Builder's Bane"],
        mine=[_w2g3_Permanent(card=lea["Mox Pearl"])],
        theirs=[_w2g3_Permanent(card=lea["Icy Manipulator"])],
    )
    mine = game.players[0].battlefield[0]

    game.cast_from_hand(
        0, "Builder's Bane", x_value=1, target_permanent_ids=[mine.permanent_id],
    )
    game.resolve_stack()
    game._settle()

    assert [p.card.name for p in game.players[1].battlefield] == ["Icy Manipulator"]
    assert game.players[0].life == 19
    assert game.players[1].life == 20, "an untouched artifact is not a loss"


def test_w2g3_seeds_of_innocence_heals_each_artifacts_own_controller(set_pool):
    """"Destroy all artifacts. They can't be regenerated. **The controller of
    each of those artifacts** gains life equal to its mana value."

    The loop is printed as the sentence's subject, and both the seat and the
    number are read off the object the iteration is on — the seat from the map
    the sweep froze before it destroyed anything (CR 608.2h), the mana value off
    the `Permanent` the loop hands round, which is a card in a graveyard by then
    (CR 400.7).
    """
    pool = set_pool("MIR")
    lea = _w2g3_lea()
    game = _w2g3_game(
        pool, ["Seeds of Innocence"],
        mine=[_w2g3_Permanent(card=lea["Mox Pearl"])],          # mana value 0
        theirs=[_w2g3_Permanent(card=lea["Icy Manipulator"]),   # 4
                _w2g3_Permanent(card=lea["Sunglasses of Urza"])],  # 3
    )

    cast = game.cast_from_hand(0, "Seeds of Innocence")
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.players[0].battlefield
    assert not game.players[1].battlefield
    assert game.players[0].life == 20, "a Mox is worth nothing to its controller"
    assert game.players[1].life == 27, "4 + 3, to the seat that controlled them"


def test_w2g3_seeds_of_innocence_leaves_the_creatures_alone(set_pool):
    """The sweep is artifacts, and the loop's printed noun is checked against
    the record rather than taken on trust — so a creature is neither destroyed
    nor counted."""
    pool = set_pool("MIR")
    lea = _w2g3_lea()
    game = _w2g3_game(
        pool, ["Seeds of Innocence"],
        theirs=[_w2g3_Permanent(card=lea["Grizzly Bears"])],
    )

    game.cast_from_hand(0, "Seeds of Innocence")
    game.resolve_stack()
    game._settle()

    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly Bears"]
    assert game.players[1].life == 20


def test_w2g3_those_permanents_still_refuse_without_a_producer(set_pool):
    """"Each of those artifacts" now reads the destroy record as well as the
    chosen-target one, and the widening stops there: an effect that neither
    chose nor destroyed anything names nothing, and the loop refuses rather than
    running over an empty list and reporting itself resolved."""
    from engine.grammar import compile_line as _compile

    alone = _compile("The controller of each of those artifacts draws a card.")
    assert alone.parsed, "the printed word order parses"
    assert alone.lowering_error == (
        "'those <permanents>' with no earlier step in this effect that chose "
        "or destroyed any"
    )

    # The same refusal from the word order the loop was already written in, so
    # the new production cannot come to admit a sentence the old one refuses.
    spelled = _compile("For each of those artifacts, its controller draws a card.")
    assert spelled.lowering_error == alone.lowering_error


def test_w2g3_all_three_sorceries_are_supported(set_pool):
    """The census reading, so a later round that moves any of this sees it."""
    pool = set_pool("MIR")
    for name in ("Reign of Terror", "Builder's Bane", "Seeds of Innocence"):
        program = _w2g3_compile(pool[name])
        assert program.supported, f"{name}: {program.reason}"


# --- W2G5: a comparison between two life totals (CR 107.1) ---
#
# Psychic Transfer needed one condition node and one rebinding, and the second
# is the half that generalises. ``PlayerLifeIs`` reads *one* seat's life; the
# number this card compares is the distance between two, which belongs to
# neither seat — so it is its own node with two player refs and one comparison.
# And "exchange life totals with **that player**" names the seat the condition
# in front of it already targeted (CR 601.2c), which is exactly what
# ``rebind_pronoun_to_condition_target`` does for an *object* pronoun and had no
# player sibling: left alone the arm reached the lowering as a referent no spell
# froze, and the exchange refused the line.

import pytest

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.oracle import compile_card_oracle


def _w2g5_transfer_game(set_pool, p1_life: int, p2_life: int):
    card = set_pool("MIR")["Psychic Transfer"]
    game = Game(players=[
        PlayerState(name="P1", life=p1_life, hand=[card]),
        PlayerState(name="P2", life=p2_life),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def test_psychic_transfer_is_supported(set_pool):
    program = compile_card_oracle(set_pool("MIR")["Psychic Transfer"])
    assert program.supported, program.reason


@pytest.mark.parametrize(
    "mine,theirs",
    [(20, 17), (20, 25), (20, 20), (20, 15), (20, 25)],
)
def test_psychic_transfer_swaps_inside_the_bound(set_pool, mine, theirs):
    """"The difference between" is unsigned (CR 107.1 has no negative
    quantities), so the card reads the same whichever player is ahead. A signed
    subtraction would make this castable only while its controller was behind —
    which is a legal-looking card that is not the printed one."""
    game = _w2g5_transfer_game(set_pool, mine, theirs)

    assert game.cast_from_hand(0, "Psychic Transfer", target_player_index=1).supported
    game.resolve_stack()

    assert (game.players[0].life, game.players[1].life) == (theirs, mine), game.log


def test_psychic_transfer_does_nothing_outside_the_bound(set_pool):
    """The gate is the card. A condition that answered True regardless would be
    an unconditional Mirror Universe for one mana less."""
    game = _w2g5_transfer_game(set_pool, 10, 20)

    assert game.cast_from_hand(0, "Psychic Transfer", target_player_index=1).supported
    game.resolve_stack()

    assert (game.players[0].life, game.players[1].life) == (10, 20), game.log


def test_the_pronoun_names_the_seat_the_condition_targeted(set_pool):
    """"…exchange life totals with **that player**." The rebinding, read off the
    compiled program rather than off a board: without it the exchange reaches a
    referent no spell froze and the whole line refuses, which costs the card
    while nothing fails."""
    compiled = compile_line(
        "If the difference between your life total and target player's life "
        "total is 5 or less, exchange life totals with that player."
    )
    assert compiled.instructions, compiled.parse_error or compiled.lowering_error
    payload = compiled.instructions[0].payload

    assert payload["condition"] == {
        "kind": "life_total_difference",
        "player": "you",
        "other": "target_player",
        "op": "le",
        "value": 5,
    }
    assert payload["then"][0].payload == {"recipient": "target"}


def test_only_a_targeted_seat_is_rebound(set_pool):
    """The rebinding rewrites ``that player`` and nothing else. A walk that
    rewrote "you" as well would put the condition's target where the caster is
    named — silently, and in a sentence that still compiles."""
    compiled = compile_line(
        "If the difference between your life total and target player's life "
        "total is 5 or less, you gain 2 life."
    )
    assert compiled.instructions, compiled.parse_error or compiled.lowering_error
    gain = compiled.instructions[0].payload["then"][0]

    assert gain.payload.get("recipient") == "caster"


# --- W2G5 (continued): a token count taken once per player (CR 111.1) ---
#
# "Each player creates a 1/1 green Cat creature token for each untapped Forest
# **they** control." Two pieces, and only the second is interesting.
#
# The recipient was one row in a table that already had "each opponent" and
# "target opponent", and the handler already knew `each_player`. The **count**
# is the part with no channel: every multiplied token count in the engine was
# either a game-wide tally (Gadrak) or a record on one permanent (Spiny
# Starfish), both of them one number computed in front of the loop over seats.
# This one is a different number for each seat, so it has to be evaluated
# inside that loop — evaluated once, every player would create as many Cats as
# the *caster's* board carried, which is a card nobody printed and which no
# two-Forest test would notice.

from engine.models import Permanent

from tests.helpers import _mk_card


def _w2g5_forest(tapped: bool = False) -> Permanent:
    return Permanent(card=_mk_card("Forest", "Basic Land - Forest", ""))


def _w2g5_weeds_game(set_pool, mine: int, theirs: int, *, tapped: int = 0):
    pool = set_pool("MIR")
    my_lands = [_w2g5_forest() for _ in range(mine)]
    game = Game(players=[
        PlayerState(
            name="P1", hand=[pool["Waiting in the Weeds"]], battlefield=my_lands
        ),
        PlayerState(name="P2", battlefield=[_w2g5_forest() for _ in range(theirs)]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    # After the untap step, or the mark this test is about would be swept before
    # the spell is ever cast.
    for land in my_lands[:tapped]:
        land.tapped = True
    return game


def _w2g5_cats(game, seat: int) -> int:
    return sum(
        1 for perm in game.controlled_by(seat) if perm.metadata.get("is_token")
    )


def test_waiting_in_the_weeds_is_supported(set_pool):
    program = compile_card_oracle(set_pool("MIR")["Waiting in the Weeds"])
    assert program.supported, program.reason


def test_each_player_counts_their_own_forests(set_pool):
    """The whole card. The two boards are deliberately different sizes: a count
    taken once in front of the loop over seats would give both players the same
    number, and it would be the caster's."""
    game = _w2g5_weeds_game(set_pool, mine=3, theirs=1)

    assert game.cast_from_hand(0, "Waiting in the Weeds").supported
    game.resolve_stack()
    game._settle()

    assert (_w2g5_cats(game, 0), _w2g5_cats(game, 1)) == (3, 1), game.log


def test_a_tapped_forest_is_not_counted(set_pool):
    """"…for each **untapped** Forest they control." The adjective is a third of
    the sentence, and a count that dropped it would be silently too large — the
    dropped-rider bug with an arithmetic face."""
    game = _w2g5_weeds_game(set_pool, mine=3, theirs=1, tapped=1)

    assert game.cast_from_hand(0, "Waiting in the Weeds").supported
    game.resolve_stack()
    game._settle()

    assert (_w2g5_cats(game, 0), _w2g5_cats(game, 1)) == (2, 1), game.log


def test_a_player_with_no_forests_creates_nothing(set_pool):
    """Zero is a number the sentence can produce, and CR 111.1 makes no token
    for it — as against a count that failed to resolve, which this test would
    not tell apart from a working one if the opponent had any Forest at all."""
    game = _w2g5_weeds_game(set_pool, mine=2, theirs=0)

    assert game.cast_from_hand(0, "Waiting in the Weeds").supported
    game.resolve_stack()
    game._settle()

    assert (_w2g5_cats(game, 0), _w2g5_cats(game, 1)) == (2, 0), game.log


def test_they_control_needs_a_distributed_subject(set_pool):
    """"They" names nobody when the sentence in front of it named nobody. The
    refusal is the point: falling back to the caster would be the same card with
    the wrong board counted, and nothing would say so."""
    compiled = compile_line(
        "Create a 1/1 green Cat creature token for each untapped Forest they control."
    )

    assert not compiled.instructions
    assert "names no seat" in (compiled.lowering_error or ""), compiled.lowering_error


# --- W3G1: Illicit Auction, the round of offers ---

import pytest as _w3g1_pytest

from engine import Game as _w3g1_Game, PlayerState as _w3g1_PlayerState
from engine.grammar.errors import GrammarError as _w3g1_GrammarError
from engine.grammar.parser import parse_line as _w3g1_parse_line
from engine.models import Permanent as _w3g1_Permanent
from engine.oracle import compile_card_oracle as _w3g1_compile


def _w3g1_board(set_pool, *, interactive=(), lives=(20, 20)):
    """A board with the auction in P1's hand and P2's creature to bid for."""
    pool = set_pool("MIR")
    victim = _w3g1_Permanent(card=pool["Femeref Knight"])
    game = _w3g1_Game(players=[
        _w3g1_PlayerState(name="P1", hand=[pool["Illicit Auction"]],
                          library=[pool["Island"]] * 5),
        _w3g1_PlayerState(name="P2", battlefield=[victim],
                          library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat, life in enumerate(lives):
        game.players[seat].life = life
    return game, victim


def _w3g1_cast(game):
    result = game.cast_from_hand(
        0, "Illicit Auction", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    return result


def _w3g1_cast_on_the_stack(game):
    """The *interactive* path: the spell is queued and both seats pass, so it
    resolves through `pass_priority` rather than through `_settle`.

    Which matters here and nowhere else in this file: `_settle` is the headless
    loop and pops the object before its prompts are drained, so only this route
    can show the spell being held on the stack while a bid is owed.
    """
    game.active_player_index = 0
    assert game.queue_from_hand(
        0, "Illicit Auction", target_player_index=1, target_permanent_index=0
    ).supported
    game.start_priority_window(0)
    game.pass_priority(0)
    return game.pass_priority(1)


def test_illicit_auction_is_supported_with_one_instruction(set_pool):
    """The whole paragraph is one effect, not five.

    Four of the printed sentences are the auction's *procedure* — who opens the
    bidding, in what order it goes round, when it stops, what the winner pays —
    and none of them is a board change on its own. A lowering that made each a
    step would have four steps nothing could perform.
    """
    program = _w3g1_compile(set_pool("MIR")["Illicit Auction"])

    assert program.supported
    kinds = [i.kind for i in program.instructions]
    assert kinds.count("bid_life_for_control") == 1
    payload = next(
        i.payload for i in program.instructions if i.kind == "bid_life_for_control"
    )
    # The opening bid is read off the printed sentence rather than assumed.
    assert payload["starting_bid"] == 0
    assert payload["targets"]["filter"] == {"type_filter": "creature"}


def test_the_procedure_sentences_are_required(set_pool):
    """The four sentences behind the offer are load-bearing.

    A card that said "each player may bid life for control of target creature"
    and then described a *different* procedure would be a different card, and
    admitting it here would be the dropped-rider bug with a whole paragraph in
    it. The production refuses rather than reading its own procedure into text
    that does not print it.
    """
    with _w3g1_pytest.raises(_w3g1_GrammarError):
        _w3g1_parse_line("Each player may bid life for control of target creature.")
    with _w3g1_pytest.raises(_w3g1_GrammarError):
        _w3g1_parse_line(
            "Each player may bid life for control of target creature. "
            "You start the bidding with a bid of 0. "
            "In reverse turn order, each player may top the high bid. "
            "The bidding ends if the high bid stands. "
            "The high bidder loses life equal to the high bid and gains "
            "control of the creature."
        )


def test_the_opening_bid_of_zero_wins_when_nobody_tops_it(set_pool):
    """Every other seat is a non-interactive default, which passes — so the
    caster takes the creature for nothing, which is what the card says happens
    when the high bid stands at 0."""
    game, victim = _w3g1_board(set_pool)

    _w3g1_cast(game)

    assert game.controller_index_of(victim) == 0
    assert [p.life for p in game.players] == [20, 20]
    assert game.pending_choices == []


def test_a_seat_that_tops_the_bid_pays_and_takes_the_creature(set_pool):
    game, victim = _w3g1_board(set_pool, interactive={1})
    _w3g1_cast(game)

    assert game.confirm_bid_life(1, 5)

    assert game.controller_index_of(victim) == 1
    assert [p.life for p in game.players] == [20, 15]
    assert game.pending_choices == []


def test_the_bidding_goes_round_until_the_high_bid_stands(set_pool):
    """A raise puts everyone else back in: P2 bids 5, P1 tops with 7, and P2 is
    asked again before the auction can end."""
    game, victim = _w3g1_board(set_pool, interactive={0, 1})
    _w3g1_cast(game)

    assert [c.player_index for c in game.pending_choices] == [1]
    assert game.confirm_bid_life(1, 5)
    # The raise re-opens the round for the seat that had already bid 0.
    assert [c.player_index for c in game.pending_choices] == [0]
    assert game.confirm_bid_life(0, 7)
    # And P1's raise re-opens it for P2, who had the high bid a moment ago.
    assert [c.player_index for c in game.pending_choices] == [1]
    assert game.confirm_bid_life(1, None)

    assert game.pending_choices == []
    assert game.controller_index_of(victim) == 0
    assert [p.life for p in game.players] == [13, 20]


def test_a_bid_that_does_not_top_the_high_bid_is_refused(set_pool):
    """The printed restriction, enforced rather than clamped. "Top the high
    bid" is what the offer says, so a bid at or under it is not a smaller
    answer — it is not an answer, and the prompt stays owed."""
    game, _victim = _w3g1_board(set_pool, interactive={0, 1})
    _w3g1_cast(game)
    assert game.confirm_bid_life(1, 5)

    assert game.confirm_bid_life(0, 5) is False
    assert game.confirm_bid_life(0, 4) is False
    assert game.confirm_bid_life(0, "seven") is False

    assert [(c.player_index, c.data["high_bid"]) for c in game.pending_choices] == [(0, 5)]


def test_a_bid_above_a_life_total_is_legal_and_lethal(set_pool):
    """No ceiling, because the card prints none.

    CR 118.3's "a player can't pay a cost without the resources" is about a
    *payment*; the winner **loses** life, so bidding past a life total is a
    legal answer that simply kills the bidder at the next state-based check
    (CR 704.5a).
    """
    game, victim = _w3g1_board(set_pool, interactive={1}, lives=(20, 4))
    _w3g1_cast(game)

    assert game.confirm_bid_life(1, 9)

    assert game.players[1].life == -5
    assert game.controller_index_of(victim) == 1


def test_the_spell_waits_on_the_stack_while_a_bid_is_owed(set_pool):
    """CR 608.2 / CR 117.3b: the auction is one resolution.

    The spell stays on the stack, the seat that owes the bid holds priority,
    and the card reaches the graveyard only with the last answer (CR 608.2n) —
    which is what the prompt registry's ``_stack_item`` link buys.
    """
    game, victim = _w3g1_board(set_pool, interactive={0, 1})

    assert _w3g1_cast_on_the_stack(game) == "awaiting_choice"

    assert [item.card.name for item in game.stack] == ["Illicit Auction"]
    assert [c.kind for c in game.pending_choices] == ["bid_life"]
    assert game.priority_player_index == 1
    assert "Illicit Auction resolved and moved to graveyard" not in game.log

    assert game.confirm_bid_life(1, 3)
    # Answering one offer arms the next, and the object is still held.
    assert [item.card.name for item in game.stack] == ["Illicit Auction"]
    assert game.confirm_bid_life(0, None)

    assert game.stack == []
    assert [c.name for c in game.players[0].graveyard] == ["Illicit Auction"]
    assert game.controller_index_of(victim) == 1
    assert game.players[1].life == 17


# --- W3G5: the search sorceries and Sealed Fate's missing player picker ---

import pytest as _pytest_w3g5

from engine import Game as _Game_w3g5, PlayerState as _PlayerState_w3g5
from engine.oracle import compile_card_oracle as _compile_w3g5
from engine.targeting import derive_cast_spec as _cast_spec_w3g5


def _w3g5_sealed_fate_game(set_pool):
    """Sealed Fate in seat 0's hand, four known cards on seat 1's library."""
    pool = set_pool("MIR")
    game = _Game_w3g5(players=[
        _PlayerState_w3g5(
            name="P1", hand=[pool["Sealed Fate"]], library=[pool["Island"]] * 6
        ),
        _PlayerState_w3g5(
            name="P2",
            library=[
                pool["Bay Falcon"], pool["Island"], pool["Mountain"], pool["Forest"]
            ],
        ),
    ])
    game.enforce_mana_costs = False
    return game


def test_sealed_fate_derives_the_opponent_picker_its_line_names(set_pool):
    """"Look at the top X cards of **target opponent's** library."

    The picker sweep's Roots class: the card reported supported, claimed every
    sentence, and derived *no* cast spec — because ``look_top_pick_to_hand`` has
    a row in the payload-keyed spec table and that row pre-empts the generic
    ``targets`` reading. The row answered only Ashnod's Cylix's ``looker`` key,
    so Sealed Fate's ``pile_owner`` description was thrown away.
    """
    pool = set_pool("MIR")
    card = pool["Sealed Fate"]

    spec = _cast_spec_w3g5(card, _compile_w3g5(card))

    assert spec is not None, "the client would send a bare cast"
    assert spec["kind"] == "player"
    # CR 115.4: "target opponent" may not choose the caster.
    assert spec.get("opponents_only") is True, spec


def test_sealed_fate_exiles_one_and_stacks_the_rest_back(set_pool):
    """The game the derivation exists for: the caster names the opponent, sees
    the top three, exiles one and puts the other two back on top."""
    game = _w3g5_sealed_fate_game(set_pool)
    game.interactive_seats = {0}

    result = game.cast_from_hand(0, "Sealed Fate", target_player_index=1, x_value=3)
    assert result.supported, result.details
    game.resolve_stack()

    prompt = next(c for c in game.pending_choices if c.kind == "look_top_pick")
    # The pile is the opponent's; the decision is the caster's (CR 608.2c).
    assert prompt.player_index == 0
    assert game.look_top_pile_index(prompt) == 1
    assert game.live_look_top_candidates(prompt) == [0, 1, 2]

    assert game.confirm_look_top_pick(0, 0)

    assert [c.name for c in game.players[1].exile] == ["Bay Falcon"]
    assert [c.name for c in game.players[1].library] == [
        "Island", "Mountain", "Forest"
    ]


def test_sealed_fate_without_a_named_opponent_looks_at_nothing(set_pool):
    """The failure the derivation caused, pinned so it stays a *refusal* rather
    than becoming a silent no-op again.

    With no seat named the handler has no pile, logs that it was given none and
    resolves having moved nothing — which is what the app did on every cast of
    this card, because the bare cast was all the client knew how to send.
    """
    game = _w3g5_sealed_fate_game(set_pool)
    game.interactive_seats = set()

    assert game.cast_from_hand(0, "Sealed Fate", x_value=3).supported
    game.resolve_stack()

    assert game.players[1].exile == []
    assert len(game.players[1].library) == 4


# --- W3G5: Natural Balance, a per-player loop with two branches ---

from engine.grammar import compile_line as _w3g5nb_compile_line  # noqa: E402
from engine.models import Permanent as _w3g5nb_Permanent  # noqa: E402


def _w3g5nb_game(set_pool, mine: int, theirs: int, interactive=()):
    """Natural Balance in seat 0's hand, with each seat holding *n* basics on
    the battlefield and a library of four basics and one creature card."""
    pool = set_pool("MIR")

    def _lands(count: int, name: str):
        return [_w3g5nb_Permanent(card=pool[name]) for _ in range(count)]

    game = _Game_w3g5(players=[
        _PlayerState_w3g5(
            name="P1", hand=[pool["Natural Balance"]],
            battlefield=_lands(mine, "Forest"),
            library=[pool["Forest"], pool["Mountain"], pool["Plains"],
                     pool["Swamp"], pool["Bay Falcon"]],
        ),
        _PlayerState_w3g5(
            name="P2", battlefield=_lands(theirs, "Island"),
            library=[pool["Island"], pool["Plains"], pool["Swamp"],
                     pool["Mountain"], pool["Bay Falcon"]],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w3g5nb_lands(game, seat: int) -> int:
    return sum(
        1 for perm in game.controlled_by(seat) if perm.card.primary_type == "land"
    )


def _w3g5nb_resolve(game):
    assert game.cast_from_hand(0, "Natural Balance").supported
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game._settle()


@_pytest_w3g5.mark.parametrize(
    "mine, theirs, expected",
    [
        (8, 2, (5, 5)),   # one over, one under
        (6, 4, (5, 5)),   # both boundaries: "six or more" and "four or fewer"
        (6, 5, (5, 5)),   # five is in neither sentence
        (5, 5, (5, 5)),   # nobody is in either sentence
        (9, 0, (5, 4)),   # a library holding four basics finds only four
    ],
)
def test_natural_balance_moves_every_seat_toward_five(
    set_pool, mine, theirs, expected
):
    """"Each player who controls six or more lands … Each player who controls
    four or fewer lands …"

    The two memberships are the point, and the boundaries are where a
    difference-taking implementation would be wrong: a seat on exactly five is
    in neither sentence, and a seat on six sacrifices one rather than being left
    alone. The last row is CR 701.23b — a search may find fewer than it names,
    and a library holding two basics is the board that says so.
    """
    game = _w3g5nb_game(set_pool, mine, theirs)

    _w3g5nb_resolve(game)

    assert (_w3g5nb_lands(game, 0), _w3g5nb_lands(game, 1)) == expected, game.log


def test_natural_balance_only_finds_basic_lands(set_pool):
    """"…search their library for up to X **basic land** cards."

    Both halves of the restriction are enforced, and each is a way the search
    could quietly be a better card: the creature card in the library is not a
    land, and a nonbasic would not be basic. The AI seat takes the maximum it
    is allowed, so what it left behind is the whole of the check.
    """
    game = _w3g5nb_game(set_pool, 5, 1)

    _w3g5nb_resolve(game)

    assert sorted(p.card.name for p in game.controlled_by(1)) == [
        "Island", "Island", "Mountain", "Plains", "Swamp",
    ]
    assert [c.name for c in game.players[1].library] == ["Bay Falcon"]


def test_natural_balance_sacrifices_are_the_players_own(set_pool):
    """"…chooses five lands they control and sacrifices the rest."

    Each seat gives up its own lands, into its own graveyard — the removals are
    the standing forced-sacrifice prompt, one per seat that owes one, rather
    than the spell's controller choosing for everybody.
    """
    game = _w3g5nb_game(set_pool, 8, 7)

    _w3g5nb_resolve(game)

    assert [c.name for c in game.players[0].graveyard] == [
        "Forest", "Forest", "Forest", "Natural Balance",
    ]
    assert [c.name for c in game.players[1].graveyard] == ["Island", "Island"]


def test_natural_balance_asks_the_seat_that_owes_the_choice(set_pool):
    """An interactive seat is *asked* which lands go, and the opponent's search
    is queued for the opponent — two prompts, two owners, neither of them the
    spell's controller deciding for the other."""
    game = _w3g5nb_game(set_pool, 7, 3, interactive=(0,))

    assert game.cast_from_hand(0, "Natural Balance").supported
    game.resolve_stack()

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("sacrifice", 0), ("search_library", 1),
    ]
    # Nothing has moved while the choice is owed.
    assert _w3g5nb_lands(game, 0) == 7


def test_the_four_printed_numbers_have_to_agree(set_pool):
    """The card prints four numbers and they are one: "six or more" is one over
    the target, "four or fewer" one under it, and "five minus the number of
    lands they control" counts up to it.

    A printing whose numbers disagreed would be a different card, and storing
    four fields would have made it a coin-toss which one the handler believed.
    So the production checks them and refuses.
    """
    compiled = _w3g5nb_compile_line(
        "Each player who controls six or more lands chooses four lands they "
        "control and sacrifices the rest. Each player who controls four or "
        "fewer lands may search their library for up to X basic land cards and "
        "put them onto the battlefield, where X is five minus the number of "
        "lands they control. Then each player who searched their library this "
        "way shuffles."
    )

    assert not compiled.instructions
    assert "do not agree" in (compiled.parse_error or ""), compiled.parse_error


# --- W3G4: Superior Numbers, a difference of two board counts ---
#
# "Superior Numbers deals damage to target creature equal to the number of
#  creatures you control in excess of the number of creatures target opponent
#  controls."
#
# One printed quantity with two counted halves and two different seats.
# `ast.Minus` carries the arithmetic, `count_spec` builds both halves so each
# means what the same noun phrase means printed on its own, and the subtrahend
# rides a **scope** (`owner: "target_opponent"`) rather than a controller
# filter — nothing downstream tests a controller key, so a narrowing there is a
# count taken on the wrong battlefield.
#
# "In excess of" clamps at zero: a board with fewer creatures exceeds the
# opponent's by nothing (CR 107.1b — there is no negative damage to deal).

import pytest as _w3g4s_pytest  # noqa: E402

from engine import Game as _w3g4s_Game, PlayerState as _w3g4s_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w3g4s_load,  # noqa: E402
                                manifest_set_path as _w3g4s_path)
from engine.grammar import compile_line as _w3g4s_compile  # noqa: E402
from engine.models import Permanent as _w3g4s_Permanent  # noqa: E402


def _w3g4s_lea():
    return {card.name: card for card in _w3g4s_load(_w3g4s_path("LEA"))}


def _w3g4s_board(pool, mine: int, theirs: int, seats: int = 2):
    """P0 holds the spell with *mine* creatures; the last seat has *theirs*
    plus the Shivan Dragon this aims at, so the victim is always index 0."""
    lea = _w3g4s_lea()
    victim = _w3g4s_Permanent(card=lea["Shivan Dragon"])
    players = [
        _w3g4s_PlayerState(
            name="P0", hand=[pool["Superior Numbers"]],
            battlefield=[_w3g4s_Permanent(card=lea["Grizzly Bears"])
                         for _ in range(mine)],
            library=[lea["Island"]] * 6,
        )
    ]
    for seat in range(1, seats):
        extra = [victim] if seat == seats - 1 else []
        players.append(_w3g4s_PlayerState(
            name=f"P{seat}",
            battlefield=extra + [_w3g4s_Permanent(card=lea["Hill Giant"])
                                 for _ in range(theirs if seat == seats - 1 else 0)],
            library=[lea["Island"]] * 6,
        ))
    game = _w3g4s_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, victim


@_w3g4s_pytest.mark.parametrize(
    "mine,theirs,expected",
    [
        (4, 0, 3),   # four of mine against the Dragon alone
        (4, 2, 1),   # …and two more of theirs
        (1, 3, 0),   # behind on board: "in excess of" is nothing, not -3
        (2, 1, 0),   # level
    ],
)
def test_w3g4_superior_numbers_is_the_difference_both_ways(
    set_pool, mine, theirs, expected
):
    """The sign is (mine - theirs), and the floor is zero."""
    pool = set_pool("MIR")
    game, victim = _w3g4s_board(pool, mine, theirs)

    cast = game.cast_from_hand(
        0, "Superior Numbers", target_player_index=1, target_permanent_index=0
    )
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert victim.damage_marked == expected, game.log


def test_w3g4_superior_numbers_counts_an_opponent_not_the_caster(set_pool):
    """CR 102.3: a player is never their own opponent.

    The client picks only the creature, so the seat the subtrahend is counted
    on arrives as the resolution's default — and aiming at one's *own* creature
    makes that default the caster. Counting the caster's board on both sides of
    the subtraction is always zero, which is a spell reporting supported and
    doing nothing; the scope resolves to the first living opponent instead."""
    pool = set_pool("MIR")
    lea = _w3g4s_lea()
    mine = [_w3g4s_Permanent(card=lea["Grizzly Bears"]) for _ in range(3)]
    game = _w3g4s_Game(players=[
        _w3g4s_PlayerState(name="P0",
                           battlefield=[_w3g4s_Permanent(card=lea["Shivan Dragon"])],
                           library=[lea["Island"]] * 6),
        _w3g4s_PlayerState(name="P1", library=[lea["Island"]] * 6),
        _w3g4s_PlayerState(name="P2", hand=[pool["Superior Numbers"]],
                           battlefield=mine, library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    # No seat on the wire, and the creature aimed at is the caster's own.
    game.cast_from_hand(2, "Superior Numbers", target_permanent_index=0)
    game.resolve_stack()
    game._settle()

    # 3 of mine minus the 1 the first opponent controls, not 3 minus 3.
    assert "dealt 2 damage" in " ".join(game.log), game.log


def test_w3g4_superior_numbers_offers_every_creature_as_the_target(set_pool):
    """"Target creature" narrows nothing — the printed restriction is on the
    *count*, not on what may be damaged."""
    pool = set_pool("MIR")
    game, _ = _w3g4s_board(pool, 2, 1)

    spec = game.cast_target_spec(0, pool["Superior Numbers"])

    assert spec["kind"] == "creature"
    assert len(spec["valid_targets"]) == 4, spec["valid_targets"]


def test_w3g4_a_difference_counted_on_no_named_seat_refuses(set_pool):
    """The subtrahend's whole content is *whose* board it reads, so a phrase
    naming a seat no handler can resolve refuses rather than counting the
    caster's own board — which would make the spell deal zero on a card
    reporting itself supported."""
    compiled = _w3g4s_compile(
        "Probe deals damage to target creature equal to the number of creatures "
        "you control in excess of the number of creatures you control.",
        card_name="Probe",
    )

    assert compiled.parsed
    assert not compiled.instructions
    assert "target opponent" in (compiled.lowering_error or ""), (
        compiled.lowering_error
    )

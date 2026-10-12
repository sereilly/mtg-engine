"""Odyssey sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

import pytest as _w1g2_pytest

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_duel(set_pool, hand, *, graveyard=0):
    """A two-seat game with costs off, seat 0 holding *hand* (card names from
    Odyssey) with *graveyard* cards in its graveyard, in its main phase."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_Game(players=[
        _w1g2_PlayerState(
            "Caster", library=[lea["Forest"]] * 10, hand=[ody[name] for name in hand],
        ),
        _w1g2_PlayerState("Bystander", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.players[0].graveyard.extend([lea["Grizzly Bears"]] * graveyard)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game  # _w1g2_duel


def _w1g2_put(game, seat, card):
    permanent = _w1g2_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put


def _w1g2_names(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))  # _w1g2_names


# ---------------------------------------------------------------------------
# Epicenter
# ---------------------------------------------------------------------------

def test_epicenter_below_threshold_costs_the_target_one_land(set_pool):
    """"Target player sacrifices a land of their choice." One land, the
    targeted player's, and the caster's own lands are untouched."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Epicenter"], graveyard=6)
    for _ in range(3):
        _w1g2_put(game, 0, lea["Forest"])
        _w1g2_put(game, 1, lea["Island"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])

    assert game.queue_from_hand(0, "Epicenter", target_player_index=1).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g2_names(game, 0) == ["Forest"] * 3
    assert _w1g2_names(game, 1) == ["Grizzly Bears", "Island", "Island"]
    assert game.is_on_battlefield(bears)
    assert [card.name for card in game.players[1].graveyard] == ["Island"]


def test_epicenter_at_threshold_takes_every_land_instead(set_pool):
    """"Threshold — **Each player** sacrifices all lands they control
    **instead** if there are seven or more cards in your graveyard." The
    replacement names somebody else outright: every land on both sides goes,
    creatures stay, and the one-land sacrifice does not happen as well — the
    targeted player loses three lands, not four of a larger board's."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Epicenter"], graveyard=7)
    for _ in range(3):
        _w1g2_put(game, 0, lea["Forest"])
        _w1g2_put(game, 1, lea["Island"])
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Grizzly Bears"])

    assert game.queue_from_hand(0, "Epicenter", target_player_index=1).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g2_names(game, 0) == ["Grizzly Bears"]
    assert _w1g2_names(game, 1) == ["Grizzly Bears"]
    assert game.is_on_battlefield(mine) and game.is_on_battlefield(theirs)
    assert len(game.players[1].graveyard) == 3
    assert len(game.players[0].graveyard) == 7 + 3 + 1
    assert sum("sacrificed" in line for line in game.log) == 2


def test_epicenter_still_announces_its_target_player_at_threshold(set_pool):
    """The target is chosen as the spell is cast (CR 601.2c), when nobody
    knows which sentence will run: the picker offers players whichever the
    graveyard says, and a permanent is not a legal announcement."""
    lea = set_pool("LEA")
    card = set_pool("ODY")["Epicenter"]
    for graveyard in (0, 7):
        game = _w1g2_duel(set_pool, ["Epicenter"], graveyard=graveyard)
        island = _w1g2_put(game, 1, lea["Island"])
        spec = game.cast_target_spec(0, card)
        assert spec["requires_target"], graveyard
        assert {entry["kind"] for entry in spec["valid_targets"]} == {"player"}
        refused = game.queue_from_hand(
            0, "Epicenter", target_permanent_ids=[island.permanent_id],
        )
        assert not refused.supported, (graveyard, refused.details)
        assert game.players[0].hand == [card]


# ---------------------------------------------------------------------------
# Kirtar's Wrath
# ---------------------------------------------------------------------------

def _w1g2_wrath_board(set_pool, graveyard):
    """Kirtar's Wrath in hand over a board with a regeneration shield up on
    the opponent's Drudge Skeletons."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Kirtar's Wrath"], graveyard=graveyard)
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Craw Wurm"])
    skeletons = _w1g2_put(game, 1, lea["Drudge Skeletons"])
    assert game.activate_permanent_ability(1, "Drudge Skeletons").supported
    return game, (mine, theirs, skeletons)  # _w1g2_wrath_board


@_w1g2_pytest.mark.parametrize("graveyard, spirits", [(6, 0), (7, 2)])
def test_kirtars_wrath_destroys_everything_and_regeneration_does_not_help(
    set_pool, graveyard, spirits,
):
    """"Destroy all creatures. They can't be regenerated. / Threshold — If
    there are seven or more cards in your graveyard, **instead** destroy all
    creatures, then create two 1/1 white Spirit creature tokens with flying.
    Creatures destroyed this way can't be regenerated." Either way every
    creature dies and a regeneration shield is no answer (CR 701.19c); at
    threshold two Spirits arrive *after* the sweep and survive it."""
    game, creatures = _w1g2_wrath_board(set_pool, graveyard)

    assert game.cast_from_hand(0, "Kirtar's Wrath").supported

    assert not any(game.is_on_battlefield(creature) for creature in creatures)
    assert _w1g2_names(game, 1) == []
    tokens = list(game.controlled_by(0))
    assert len(tokens) == spirits
    for token in tokens:
        assert token.card.name == "Spirit Token"
        assert (token.effective_power, token.effective_toughness) == (1, 1)
        assert set(token.effective_colors) == {"W"}
        assert game._has_keyword(token, "flying")
    assert sum("were destroyed" in line for line in game.log) == 1, "one sweep, not two"


def test_kirtars_wrath_marks_the_replacing_sweep_unregenerable_too(set_pool):
    """The rider is printed twice, once per sentence, and each has to reach
    its own sweep: "Creatures destroyed this way can't be regenerated" follows
    a "…, then create …" sentence, so it marks the destroy inside it. Read
    onto the replaced arm alone, the threshold sweep could be regenerated
    from."""
    program = _w1g2_compile(set_pool("ODY")["Kirtar's Wrath"])
    (gate,) = program.instructions
    assert gate.kind == "if_then"
    then, otherwise = gate.payload["then"], gate.payload["else"]
    assert [step.kind for step in then] == ["destroy_all_creatures", "create_token"]
    assert [step.kind for step in otherwise] == ["destroy_all_creatures"]
    assert then[0].payload.get("bypass_regeneration") is True
    assert otherwise[0].payload.get("bypass_regeneration") is True
    assert then[1].payload["count"] == 2


def test_the_threshold_sorceries_compile_every_printed_sentence(set_pool):
    """None is supported on its first sentence alone: the whole card is one
    conditional whose condition is the graveyard count."""
    ody = set_pool("ODY")
    for name in ("Epicenter", "Kirtar's Wrath", "Shower of Coals"):
        program = _w1g2_compile(ody[name])
        assert program.supported, name
        assert [i.kind for i in program.instructions] == ["if_then"], name
        assert program.instructions[0].payload["condition"]["value"] == 7


# ---------------------------------------------------------------------------
# Shower of Coals
# ---------------------------------------------------------------------------

def _w1g2_shower_board(set_pool, graveyard):
    """Shower of Coals in hand; the opponent has Bears (2/2), a Wurm (6/4)
    and a Giant (3/3), the caster a Wurm of its own."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Shower of Coals"], graveyard=graveyard)
    mine = _w1g2_put(game, 0, lea["Craw Wurm"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    wurm = _w1g2_put(game, 1, lea["Craw Wurm"])
    giant = _w1g2_put(game, 1, lea["Hill Giant"])
    return game, mine, bears, wurm, giant  # _w1g2_shower_board


def _w1g2_slot(game, permanent):
    return (game.controller_index_of(permanent), game.battlefield_index_of(permanent))  # _w1g2_slot


@_w1g2_pytest.mark.parametrize("graveyard, each", [(6, 2), (7, 4)])
def test_shower_of_coals_deals_two_or_four_to_each_of_up_to_three(
    set_pool, graveyard, each,
):
    """"Shower of Coals deals 2 damage to each of up to three targets. /
    Threshold — Shower of Coals deals 4 damage to **each of those permanents
    and/or players** instead if there are seven or more cards in your
    graveyard." One list — a face and two creatures here — announced once, and
    every target on it takes the whole amount of whichever sentence runs:
    2 kills the Bears and not the Wurm, 4 kills both. The Giant was never
    named and is never touched."""
    game, _mine, bears, wurm, giant = _w1g2_shower_board(set_pool, graveyard)

    assert game.queue_from_hand(
        0, "Shower of Coals",
        divided_targets=[(1, None), _w1g2_slot(game, bears), _w1g2_slot(game, wurm)],
    ).supported
    _w1g2_resolve_stack(game)
    game._settle()

    assert game.players[1].life == 20 - each and game.players[0].life == 20
    assert not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(wurm) is (each < 4)
    assert game.is_on_battlefield(giant)
    assert sum("Shower of Coals dealt" in line for line in game.log) == 3
    assert all(
        f"dealt {each} damage" in line
        for line in game.log if "Shower of Coals dealt" in line
    )


def test_shower_of_coals_holds_its_list_to_three_different_targets(set_pool):
    """CR 601.2c: "up to three" is a ceiling the caster may fall short of and
    never exceed, one instance of the word names each target once, and the
    card — not the caster — says what each gets. Every refusal leaves the
    spell in hand."""
    card = set_pool("ODY")["Shower of Coals"]
    game, mine, bears, wurm, giant = _w1g2_shower_board(set_pool, 7)
    spec = game.cast_target_spec(0, card)
    assert (spec["kind"], spec["division"], spec["max_targets"]) == ("divided", "each", 3)
    assert {entry["kind"] for entry in spec["valid_targets"]} == {"player", "permanent"}

    four = game.queue_from_hand(0, "Shower of Coals", divided_targets=[
        (1, None), _w1g2_slot(game, bears), _w1g2_slot(game, wurm), _w1g2_slot(game, giant),
    ])
    twice = game.queue_from_hand(
        0, "Shower of Coals", divided_targets=[(1, None), (1, None)],
    )
    sized = game.queue_from_hand(
        0, "Shower of Coals", divided_targets=[(*_w1g2_slot(game, bears), 9)],
    )
    assert "at most 3 targets" in four.details
    assert "different" in twice.details
    assert "printed, not announced" in sized.details
    assert not (four.supported or twice.supported or sized.supported)
    assert game.players[0].hand == [card] and game.stack == []

    assert game.cast_from_hand(
        0, "Shower of Coals", divided_targets=[_w1g2_slot(game, giant)],
    ).supported
    assert not game.is_on_battlefield(giant)
    assert game.is_on_battlefield(bears) and game.is_on_battlefield(mine)
    assert game.players[1].life == 20


def test_shower_of_coals_reads_threshold_as_it_resolves_and_drops_a_gone_target(set_pool):
    """Six cards as it is cast and a seventh arriving in response is 4 each
    (CR 608.2h). A target that left in response is dealt nothing and nothing
    takes its place (CR 608.2b); the rest of the list still burns."""
    lea = set_pool("LEA")
    game, _mine, bears, wurm, giant = _w1g2_shower_board(set_pool, 6)
    assert game.queue_from_hand(
        0, "Shower of Coals",
        divided_targets=[_w1g2_slot(game, bears), _w1g2_slot(game, wurm), (1, None)],
    ).supported

    game.players[0].graveyard.append(lea["Forest"])
    game.remove_from_battlefield(bears)
    _w1g2_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(wurm), "4, not 2"
    assert game.is_on_battlefield(giant), "never named"
    assert game.players[1].life == 16

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4_pytest

from engine import Game as _w1g4_Game, PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names.

    Odyssey over Stronghold over Alpha: the furniture is Alpha's, and Megrim —
    which is how a discard is seen to have gone through its seam — is
    Stronghold's.
    """
    pool = {**set_pool("LEA"), **set_pool("STH"), **set_pool("ODY")}
    seats = [
        _w1g4_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g4_Game(players=seats)
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            game._put_permanent_onto_battlefield(
                seat, _w1g4_Permanent(card=pool[name]), None
            )
    return game


def _w1g4_names(cards):
    return [card.name for card in cards]


# --- Mind Burst: a *chosen* discard of X cards -------------------------------

def test_mind_burst_makes_its_target_choose_one_plus_the_bursts(set_pool):
    """One plus two in graveyards is three, and the discarding player picks
    them — the lowering refused a chosen discard of X on the ground that the
    only variable handler discarded at random, long after the chosen handler
    began sizing its prompt from X."""
    game = _w1g4_duel(
        set_pool, hand0=["Mind Burst"], gy0=["Mind Burst"], gy1=["Mind Burst"],
        hand1=["Grizzly Bears", "Forest", "Island", "Swamp", "Mountain"],
    )
    game.interactive_seats.add(1)
    assert game.cast_from_hand(0, "Mind Burst", target_player_index=1).supported
    prompt = next(c for c in game.pending_choices if c.kind == "discard")
    assert prompt.player_index == 1 and prompt.data["count"] == 3
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 2
    assert len(game.players[1].graveyard) == 4


def test_mind_burst_takes_what_there_is_from_a_short_hand(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Mind Burst"], gy0=["Mind Burst", "Mind Burst"],
        hand1=["Forest"],
    )
    assert game.cast_from_hand(0, "Mind Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert game.players[1].hand == []
    assert "Forest" in _w1g4_names(game.players[1].graveyard)


def test_a_chosen_discard_of_a_cast_x_reads_the_announced_number(set_pool):
    """The same handler under an X the caster pays for rather than counts."""
    warp = _w1g4_mk_card(
        "Mind Wrench", "{X}{B}", "Sorcery", "Target player discards X cards."
    )
    assert _w1g4_compile(warp).supported
    game = _w1g4_duel(set_pool, hand1=["Forest", "Island", "Swamp"])
    game.players[0].hand.append(warp)
    assert game.cast_from_hand(
        0, "Mind Wrench", target_player_index=1, x_value=2
    ).supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 1


# --- Hint of Insanity: "…the same name as another card in their hand" --------

def test_hint_of_insanity_discards_every_nonland_card_held_in_multiples(set_pool):
    """A pair and a triple go; the two Forests share a name and are lands, and
    the lone Wurm shares a name with nothing. Nobody chooses, so no prompt."""
    game = _w1g4_duel(
        set_pool, hand0=["Hint of Insanity"],
        hand1=["Grizzly Bears", "Forest", "Lightning Bolt", "Grizzly Bears",
               "Forest", "Craw Wurm", "Lightning Bolt", "Lightning Bolt"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert game.pending_choices == []
    assert _w1g4_names(game.players[1].hand) == ["Forest", "Forest", "Craw Wurm"]
    assert sorted(_w1g4_names(game.players[1].graveyard)) == [
        "Grizzly Bears", "Grizzly Bears",
        "Lightning Bolt", "Lightning Bolt", "Lightning Bolt",
    ]
    assert any(
        line.startswith("P1 reveals their hand") for line in game.log
    ), "the reveal is its own sentence and happens whatever is discarded"


def test_hint_of_insanity_with_no_pair_reveals_and_discards_nothing(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Hint of Insanity"],
        hand1=["Grizzly Bears", "Forest", "Forest", "Craw Wurm"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert len(game.players[1].hand) == 4 and game.players[1].graveyard == []
    assert any(line.startswith("P1 reveals their hand") for line in game.log)


def test_hint_of_insanity_at_its_own_caster_does_not_pair_with_itself(set_pool):
    """The copy being cast is on the stack, so a second Hint in hand shares a
    name with no *other card in that hand* — and the two Bears go."""
    game = _w1g4_duel(
        set_pool,
        hand0=["Hint of Insanity", "Hint of Insanity", "Grizzly Bears", "Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=0
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].hand) == ["Hint of Insanity"]
    assert game.players[1].hand == []


def test_hint_of_insanity_discards_through_the_discard_seam(set_pool):
    """Megrim sees each card: the discards are announced, not written."""
    game = _w1g4_duel(
        set_pool, hand0=["Hint of Insanity"],
        hand1=["Grizzly Bears", "Grizzly Bears", "Forest"], bf0=["Megrim"],
    )
    assert game.cast_from_hand(
        0, "Hint of Insanity", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 16


@_w1g4_pytest.mark.parametrize("line", [
    # "Another card" with no pile behind it compares against nobody knows what.
    "Target player discards all nonland cards with the same name as another card.",
    # A pile other than the one being discarded from is a different sentence.
    "Target player discards all nonland cards with the same name as another "
    "card in your hand.",
    # A card phrase compared with a permanent names two kinds of object.
    "Target player discards all nonland cards with the same name as another "
    "permanent.",
])
def test_the_shared_name_discard_refuses_what_it_cannot_compare(line):
    hint = _w1g4_mk_card("Odd Hint", "{B}", "Sorcery", line)
    assert not _w1g4_compile(hint).supported


# --- Haunting Echoes: a sweep of one graveyard, then a strip by every name ---

def test_haunting_echoes_exiles_the_graveyard_and_every_library_copy(set_pool):
    """The basic land stays in the graveyard and its copy in the library; the
    nonbasic land, the creature and the instant go from both. The caster's own
    graveyard and library are not touched."""
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"],
        gy1=["Grizzly Bears", "Forest", "Lightning Bolt", "Bayou"],
        lib1=["Grizzly Bears", "Forest", "Lightning Bolt", "Craw Wurm",
              "Grizzly Bears", "Bayou", "Island"],
        gy0=["Craw Wurm"], lib0=["Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Forest"]
    assert sorted(_w1g4_names(game.players[1].library)) == [
        "Craw Wurm", "Forest", "Island",
    ]
    assert sorted(_w1g4_names(game.players[1].exile)) == [
        "Bayou", "Bayou", "Grizzly Bears", "Grizzly Bears", "Grizzly Bears",
        "Lightning Bolt", "Lightning Bolt",
    ]
    assert _w1g4_names(game.players[0].library) == ["Grizzly Bears"]
    assert _w1g4_names(game.players[0].graveyard) == ["Craw Wurm", "Haunting Echoes"]
    assert game.players[0].exile == []


def test_haunting_echoes_over_only_basic_lands_strips_nothing(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"], gy1=["Forest", "Island"],
        lib1=["Forest", "Island", "Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Forest", "Island"]
    assert len(game.players[1].library) == 3 and game.players[1].exile == []


def test_haunting_echoes_may_be_aimed_at_its_caster(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"], gy0=["Grizzly Bears"],
        lib0=["Grizzly Bears", "Craw Wurm"], lib1=["Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=0
    ).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].library) == ["Craw Wurm"]
    assert _w1g4_names(game.players[0].exile) == ["Grizzly Bears", "Grizzly Bears"]
    assert _w1g4_names(game.players[1].library) == ["Grizzly Bears"]


def test_haunting_echoes_shuffles_the_library_it_searched(set_pool):
    """CR 701.24. Fifteen distinct-order cards and a seeded RNG: the survivors'
    order changes, which an unshuffled strip would leave as it was."""
    import random

    library = (["Grizzly Bears"] + ["Forest", "Island", "Swamp", "Mountain",
               "Plains", "Craw Wurm", "Scryb Sprites", "Black Lotus",
               "Shivan Dragon", "Giant Growth", "Fireball", "Lightning Bolt",
               "Sol Ring", "Mox Pearl"])
    game = _w1g4_duel(
        set_pool, hand0=["Haunting Echoes"], gy1=["Grizzly Bears"], lib1=library,
    )
    random.seed(11)
    assert game.cast_from_hand(
        0, "Haunting Echoes", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    after = _w1g4_names(game.players[1].library)
    assert sorted(after) == sorted(library[1:])
    assert after != library[1:]


@_w1g4_pytest.mark.parametrize("text", [
    # No sweep in front of the loop: "exiled this way" names nothing.
    "For each card exiled this way, search target player's library for all "
    "cards with the same name as that card and exile them. Then that player "
    "shuffles.",
    # CR 701.24: a library search ends with the shuffle.
    "Exile all cards from target player's graveyard other than basic land "
    "cards. For each card exiled this way, search that player's library for "
    "all cards with the same name as that card and exile them.",
    # A loop over a narrower set than the sweep recorded.
    "Exile all cards from target player's graveyard. For each creature card "
    "exiled this way, search that player's library for all cards with the "
    "same name as that card and exile them. Then that player shuffles.",
    # "That card" outside any loop.
    "Search target player's library for all cards with the same name as that "
    "card and exile them. Then that player shuffles.",
])
def test_the_strip_by_exiled_names_refuses_without_its_sweep_and_shuffle(text):
    echoes = _w1g4_mk_card("Odd Echoes", "{B}", "Sorcery", text)
    assert not _w1g4_compile(echoes).supported


def test_a_sweep_of_a_chosen_graveyard_names_its_player(set_pool):
    """The sweep on its own, on an invented card: "target opponent's" pile and
    a narrowing the card matcher answers, with the caster's pile left alone."""
    purge = _w1g4_mk_card(
        "Grave Purge", "{B}", "Sorcery",
        "Exile all creature cards from target opponent's graveyard.",
    )
    assert _w1g4_compile(purge).supported
    game = _w1g4_duel(
        set_pool, gy0=["Grizzly Bears"], gy1=["Grizzly Bears", "Forest", "Craw Wurm"],
    )
    game.players[0].hand.append(purge)
    spec = game.cast_target_spec(0, purge)
    assert [t["seat"] for t in spec["valid_targets"]] == [1]
    assert game.cast_from_hand(0, "Grave Purge", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Forest"]
    assert _w1g4_names(game.players[0].graveyard) == ["Grizzly Bears", "Grave Purge"]


# --- Buried Alive, Diabolic Tutor, Extract -----------------------------------

_W1G4_LIBRARY = ["Forest", "Grizzly Bears", "Craw Wurm", "Scryb Sprites",
                 "Black Lotus", "Island", "Shivan Dragon"]


def test_buried_alive_puts_up_to_three_creature_cards_into_the_graveyard(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Buried Alive"], lib0=_W1G4_LIBRARY)
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Buried Alive").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["count"] == 3 and prompt.data["up_to"]
    assert prompt.data["card_type"] == "creature"
    assert prompt.data["destinations"] == ["graveyard"] * 3
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    buried = [n for n in _w1g4_names(game.players[0].graveyard) if n != "Buried Alive"]
    assert len(buried) == 3
    assert set(buried) <= {"Grizzly Bears", "Craw Wurm", "Scryb Sprites", "Shivan Dragon"}
    assert len(game.players[0].library) == 4 and game.players[0].hand == []


def test_buried_alive_over_a_library_of_no_creatures_finds_nothing(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Buried Alive"], lib0=["Forest", "Island"])
    assert game.cast_from_hand(0, "Buried Alive").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g4_names(game.players[0].graveyard) == ["Buried Alive"]
    assert len(game.players[0].library) == 2


def test_diabolic_tutor_finds_any_card_and_does_not_tell_the_table_which(set_pool):
    """A search with no reveal into a hidden zone: the log every viewer is
    sent says a card went to hand and never names it."""
    game = _w1g4_duel(set_pool, hand0=["Diabolic Tutor"], lib0=_W1G4_LIBRARY)
    assert game.cast_from_hand(0, "Diabolic Tutor").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    (found,) = _w1g4_names(game.players[0].hand)
    assert len(game.players[0].library) == 6
    assert not any(found in line for line in game.log)
    assert any("put a card into hand" in line for line in game.log)


def test_extract_exiles_a_card_from_the_library_of_the_player_it_names(set_pool):
    """The caster searches and chooses; the card goes to its owner's exile and
    the searched player's library is the one that shrinks."""
    game = _w1g4_duel(
        set_pool, hand0=["Extract"], lib0=["Swamp", "Plains"], lib1=_W1G4_LIBRARY,
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Extract", target_player_index=1).supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.player_index == 0, "CR 608.2c: the spell's controller chooses"
    assert prompt.data["zone_seat"] == 1 and prompt.data["destination"] == "exile"
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    assert len(game.players[1].library) == 6 and len(game.players[1].exile) == 1
    assert len(game.players[0].library) == 2 and game.players[0].exile == []

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

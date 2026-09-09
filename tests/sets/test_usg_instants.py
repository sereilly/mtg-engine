"""Urza's Saga instants.

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


# --- W1G1: cycling (CR 702.29) ---
import pytest

from engine import Game, PlayerState
from engine.activation_zones import HAND
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The six instants with cycling. Five of them (all but Brand) were reported
#: **supported** before the CR 702.29a rewrite existed — a spell is supported
#: when any of its lines is, and their effect line always compiled — so the
#: keyword sat in `parse_coverage.py --set USG` as an unclaimed line and in no
#: other instrument at all. That is the population a refusal census cannot
#: reach, and it is why these tests cycle the card in a game rather than
#: asserting that it compiles.
_G1_CYCLING_INSTANTS = ("Clear", "Rescind", "Expunge", "Brand", "Scrap", "Lull")


def _g1_spell_game(card, *, library=4):
    """Seat 0 holds *card* over a library of copies of it."""
    player = PlayerState(name="G1-A", hand=[card], library=[card] * library)
    game = Game(players=[player, PlayerState(name="G1-B")])
    game.enforce_mana_costs = False
    return game, player


@pytest.mark.parametrize("name", _G1_CYCLING_INSTANTS)
def test_w1g1_a_cycling_instant_is_discarded_for_a_card(set_pool, name):
    """Cycling replaces casting the spell, not part of it: the card goes to the
    graveyard, one card is drawn, and the printed effect never happens."""
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]
    # An instant is never on the battlefield, so it has no battlefield abilities
    # to confuse with the cycling one.
    assert usable_activated_abilities(program) == []

    game, player = _g1_spell_game(card)
    opponent_board = [p.card.name for p in game.players[1].battlefield]

    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)

    assert [c.name for c in player.graveyard] == [name]
    assert [c.name for c in player.hand] == [name]      # the card drawn
    assert len(player.library) == 3
    assert [p.card.name for p in game.players[1].battlefield] == opponent_board


# --- W2G3: per-player bounces and whole-table counts ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card, _mk_creature_card, resolve_stack


def _g3w2i_table(*, interactive=()):
    """Two seats, mana enforcement off, and whichever of them answers prompts.

    ``_g3w2i_`` prefixed and ending on ``return game, game.players[0],
    game.players[1]`` — SET_PLAYBOOK.md's note about a union splicing one
    helper's body onto another's signature.
    """
    game = Game(players=[PlayerState(name="W2G3I-A"), PlayerState(name="W2G3I-B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, game.players[0], game.players[1]


def _g3w2i_creature(game, seat, name):
    permanent = Permanent(card=_mk_creature_card(name, 2, 2))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def _g3w2i_cast(game, seat, card, **kwargs):
    game.players[seat].hand.append(card)
    result = game.cast_from_hand(seat, card.name, **kwargs)
    resolve_stack(game)
    return result


def test_w2g3_curfew_makes_every_player_return_one_of_their_own(set_pool):
    """"Each player returns a creature they control to its owner's hand."

    "They" agrees with "each player", so every seat is asked and every seat
    draws its candidates from its **own** battlefield. A reading that asked one
    player would leave the other's creature on the table; one that drew from a
    single battlefield would return two of the caster's.
    """
    card = set_pool("USG")["Curfew"]
    assert compile_card_oracle(card).supported

    game, alice, bob = _g3w2i_table()
    _g3w2i_creature(game, 0, "W2G3 Alice Bear")
    _g3w2i_creature(game, 1, "W2G3 Bob Bear")

    _g3w2i_cast(game, 0, card)
    game.auto_resolve_pending_choices()

    assert [c.name for c in alice.hand] == ["W2G3 Alice Bear"]
    assert [c.name for c in bob.hand] == ["W2G3 Bob Bear"]
    assert list(game.all_permanents()) == []


def test_w2g3_curfew_skips_a_player_with_no_creature(set_pool):
    """CR 608.2's "as much as possible": a seat with nothing to return is not a
    prompt with no answer, and the other seat still pays."""
    game, alice, bob = _g3w2i_table()
    _g3w2i_creature(game, 1, "W2G3 Bob Bear")

    _g3w2i_cast(game, 0, set_pool("USG")["Curfew"])
    game.auto_resolve_pending_choices()

    assert alice.hand == []
    assert [c.name for c in bob.hand] == ["W2G3 Bob Bear"]


def test_w2g3_congregate_counts_every_battlefield(set_pool):
    """"Target player gains 2 life for each creature on the battlefield."

    CR 403.1's one shared zone: the count is every seat's creatures and names
    none of them, which is exactly why it can be taken while somebody else
    gains the life. Counted on the gainer's own board it would be 4 here, and
    on the caster's 2 — so the two boards are deliberately uneven.
    """
    card = set_pool("USG")["Congregate"]
    assert compile_card_oracle(card).supported

    game, alice, bob = _g3w2i_table()
    _g3w2i_creature(game, 0, "W2G3 A1")
    _g3w2i_creature(game, 1, "W2G3 B1")
    _g3w2i_creature(game, 1, "W2G3 B2")
    before = bob.life

    _g3w2i_cast(game, 0, card, target_player_index=1)

    assert bob.life == before + 6, "three creatures on the battlefield, 2 life each"
    assert alice.life == 20, "and the caster gains none"


# --- W2G4: durations, taking abilities away, and who damage goes to ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack as _g4d_resolve


def _g4d_board(*, mine=(), theirs=(), hand0=(), life=20):
    """Two seats, mana costs off, seat 0 active. Returns ``(game, s0, s1)`` and
    ends on that tuple so no union can splice another helper onto it."""
    g4d_seat0 = PlayerState(
        name="G4-I1", battlefield=[Permanent(card=c) for c in mine],
        hand=list(hand0), life=life,
    )
    g4d_seat1 = PlayerState(
        name="G4-I2", battlefield=[Permanent(card=c) for c in theirs], life=life,
    )
    g4d_game = Game(players=[g4d_seat0, g4d_seat1])
    g4d_game.enforce_mana_costs = False
    g4d_game.active_player_index = 0
    g4d_game._sync_control()
    return g4d_game, g4d_seat0, g4d_seat1


def _g4d_creature(name, power=2, toughness=2, text=""):
    from tests.helpers import _mk_creature_card

    return _mk_creature_card(name, power, toughness, text)


def test_w2g4_symbiosis_pumps_both_creatures_it_named(set_pool):
    """Two chosen objects, one boost. Lowered through the one-target handler the
    second choice would be collected and dropped — the shape
    ``_names_several_targets`` was written to refuse everywhere it is not opted
    into."""
    pool = set_pool("USG")
    game, mine, _ = _g4d_board(
        mine=[_g4d_creature("G4D One"), _g4d_creature("G4D Two")],
        hand0=[pool["Symbiosis"]],
    )
    one, two = mine.battlefield

    assert game.cast_from_hand(
        0, "Symbiosis", target_player_index=0,
        target_permanent_index=[0, 1],
        target_permanent_ids=[one.permanent_id, two.permanent_id],
    ).supported
    _g4d_resolve(game)

    assert (one.effective_power, one.effective_toughness) == (4, 4)
    assert (two.effective_power, two.effective_toughness) == (4, 4)


def test_w2g4_the_distributive_each_says_nothing_the_count_did_not(set_pool):
    """"Two target creatures **each** get +2/+2" and "two target creatures get
    +2/+2" are one sentence; the word is consumed at the subject rather than in
    every verb's production, because it can precede any of them."""
    from engine.grammar import compile_line

    with_each = compile_line("Two target creatures each get +2/+2 until end of turn.")
    without = compile_line("Two target creatures get +2/+2 until end of turn.")
    assert with_each.usable and without.usable
    assert [(i.kind, i.payload) for i in with_each.instructions] == [
        (i.kind, i.payload) for i in without.instructions
    ]
    # …and the word is not a quantifier this can eat off a singular subject.
    assert not compile_line("Target creature each gets +2/+2 until end of turn.").parsed


def test_w2g4_humble_takes_every_ability_and_gives_them_back_at_cleanup(set_pool):
    """CR 613.1f aimed at one permanent, which the engine had only as a
    board-wide static. The record is a contribution rather than a rewrite: the
    creature's own text is untouched, and the cleanup sweep is the whole of the
    duration."""
    pool = set_pool("USG")
    angel = _g4d_creature("G4D Angel", 4, 4, "Flying")
    game, mine, theirs = _g4d_board(theirs=[angel], hand0=[pool["Humble"]])
    victim = theirs.battlefield[0]

    assert game._has_keyword(victim, "flying")
    assert game.cast_from_hand(
        0, "Humble", target_player_index=1,
        target_permanent_index=0, target_permanent_ids=[victim.permanent_id],
    ).supported
    _g4d_resolve(game)
    game._refresh_dynamic_creatures()

    assert (victim.effective_power, victim.effective_toughness) == (0, 1)
    assert not game._has_keyword(victim, "flying")
    assert victim.effective_card.oracle_text == ""
    assert victim.card.oracle_text == "Flying", "the printed card is not rewritten"

    game.resolve_cleanup_step(0)
    game._refresh_dynamic_creatures()
    assert (victim.effective_power, victim.effective_toughness) == (4, 4)
    assert game._has_keyword(victim, "flying")


def test_w2g4_the_blanket_removal_reaches_a_triggered_ability_too(set_pool):
    """Layer 6 drops the *keyword* set, and that is a third of an ability: a
    triggered one is read off the card at the trigger scan. Both go through
    ``Permanent.effective_card``, which is why one write reaches all of them."""
    pool = set_pool("USG")
    watcher = _g4d_creature(
        "G4D Watcher", 2, 2, "When this creature dies, you draw a card.",
    )
    game, mine, theirs = _g4d_board(theirs=[watcher], hand0=[pool["Humble"]])
    victim = theirs.battlefield[0]

    assert compile_card_oracle(victim.effective_card).triggered_abilities
    assert game.cast_from_hand(
        0, "Humble", target_player_index=1,
        target_permanent_index=0, target_permanent_ids=[victim.permanent_id],
    ).supported
    _g4d_resolve(game)

    assert not compile_card_oracle(victim.effective_card).triggered_abilities


def test_w2g4_a_durationless_blanket_removal_still_refuses(set_pool):
    """"All creatures lose all abilities" is a *static* ability the global-statics
    table re-derives from the board on every recompute. Claimed here it would
    become a one-shot stamp, and a creature entering afterwards would keep its
    abilities."""
    from engine.grammar import compile_line

    assert compile_line(
        "Target creature loses all abilities until end of turn."
    ).usable
    assert not compile_line("All creatures lose all abilities.").usable


def test_w2g4_outmaneuver_sends_a_blocked_creature_past_its_blocker(set_pool):
    """CR 510.1a's assignment to the blockers replaced by CR 510.1b's to the
    player, for the creatures the spell chose — and **mandatorily**: the
    attacker's controller has nothing to decline, which is the difference from
    the "you may" grant the same flag family carries."""
    pool = set_pool("USG")
    game, mine, theirs = _g4d_board(
        mine=[_g4d_creature("G4D Raider", 2, 2)],
        theirs=[_g4d_creature("G4D Wall", 0, 8)],
        hand0=[pool["Outmaneuver"]],
    )
    raider = mine.battlefield[0]
    wall = theirs.battlefield[0]
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    assert game.declare_attackers(0, {0: 1})[0]
    game.current_step = "declare_blockers"
    assert game.declare_blockers(1, {0: 0})[0]

    assert game.cast_from_hand(
        0, "Outmaneuver", x_value=1, target_player_index=0,
        target_permanent_index=[0], target_permanent_ids=[raider.permanent_id],
    ).supported
    _g4d_resolve(game)

    game.current_step = "combat_damage"
    game.resolve_all_combat_damage(0)
    assert theirs.life == 18
    assert wall.damage_marked == 0


def test_w2g4_waylay_exiles_all_three_of_the_tokens_it_made(set_pool):
    """"Exile **them**" names every token this resolution created, which no read
    of a permanent can identify (CR 400.7). The singular record holds one id, so
    a plural sentence reading it would exile one Knight and leave two."""
    pool = set_pool("USG")
    game, mine, _ = _g4d_board(hand0=[pool["Waylay"]])

    assert game.cast_from_hand(0, "Waylay").supported
    _g4d_resolve(game)
    assert [p.card.name for p in mine.battlefield] == ["Knight Token"] * 3

    game.resolve_cleanup_step(0)
    assert mine.battlefield == []
    # CR 111.7: a token ceases to exist rather than going to exile.
    assert mine.exile == []


def test_w2g4_the_plural_token_reference_refuses_without_a_maker(set_pool):
    """The gate is the producer, exactly as the singular's is: with no token
    maker in front of it the word names nothing, and an exile that silently
    found nothing is a card reporting itself supported and doing nothing."""
    from engine.grammar import compile_line

    assert compile_line(
        "Create three 2/2 white Knight creature tokens. Exile them at the "
        "beginning of the next cleanup step."
    ).usable
    assert not compile_line(
        "Exile them at the beginning of the next cleanup step."
    ).usable
    # …and the six cards that print the word about a *search* keep their own
    # reading, because the pronoun is read only where everything else refused.
    searched = compile_line("Search your library for three cards, exile them, then shuffle.")
    assert [i.kind for i in searched.instructions] == ["search_and_exile_matching"]


# --- W2G1: Redeem's shield over up to two creatures ---
from engine import Game as _G1iGame, PlayerState as _G1iPlayerState  # noqa: E402
from engine.damage_events import deal_damage as _g1i_deal  # noqa: E402
from engine.models import Permanent as _G1iPermanent  # noqa: E402
from engine.oracle import compile_card_oracle as _g1i_compile  # noqa: E402
from engine.game_types import OracleExecutionContext as _G1iContext  # noqa: E402
from engine.targeting import derive_cast_spec as _g1i_spec  # noqa: E402


def _g1i_board(pool, mine=()):
    """One seat with a board and a USG library. Ends on the control sync, this
    block's own helper tail."""
    game = _G1iGame(players=[
        _G1iPlayerState(name="G1iA", battlefield=list(mine),
                        library=[pool["Remote Isle"]] * 8),
        _G1iPlayerState(name="G1iB", library=[pool["Remote Isle"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


def test_w2g1_redeem_shields_both_chosen_creatures(set_pool):
    """"Prevent all damage that would be dealt this turn to up to two target
    creatures."

    One shield armed once per chosen recipient — the branch the handler already
    had for Energy Arc's recorded set, reached from a list the caster named
    instead. Four claims: the picker's ceiling, both chosen creatures, the one
    nobody chose, and the direction (this shield covers damage dealt *to* them
    and leaves their own alone).
    """
    pool = set_pool("USG")
    a = _G1iPermanent(card=pool["Coral Merfolk"])
    b = _G1iPermanent(card=pool["Coral Merfolk"])
    c = _G1iPermanent(card=pool["Coral Merfolk"])
    game = _g1i_board(pool, mine=[a, b, c])

    card = pool["Redeem"]
    program = _g1i_compile(card)
    assert _g1i_spec(card, program) == {
        "kind": "creature", "max_targets": 2, "distinct_targets": True,
    }

    context = _G1iContext(
        card=card, caster=game.players[0], target=game.players[0],
        target_permanent_id=[a.permanent_id, b.permanent_id],
    )
    for instruction in program.instructions:
        game._execute_oracle_instruction(instruction, context)

    assert _g1i_deal(game, {"recipient": a, "amount": 3, "source": None}).dealt == 0
    assert _g1i_deal(game, {"recipient": b, "amount": 3, "source": None,
                            "combat": True}).dealt == 0
    assert _g1i_deal(game, {"recipient": c, "amount": 3, "source": None}).dealt == 3
    assert _g1i_deal(game, {"recipient": c, "amount": 1, "source": a,
                            "combat": True}).dealt == 1, (
        "the shield is one-way: it prevents damage dealt to them, not by them"
    )


# --- W2G5: Brand — ownership, not control ---
from engine import Game, PlayerState
from engine.control import change_control
from engine.models import Permanent
from tests.helpers import resolve_stack


def test_brand_takes_back_what_an_opponent_stole(set_pool, catalog_by_name):
    """"Gain control of all permanents you own. (This effect lasts
    indefinitely.)"

    CR 108.3: ownership is where the card started, wherever it is now — which
    is the whole of what this card does. Read as a *controller* narrowing the
    spell would be a blank, so the assertion is a permanent an opponent
    currently controls coming back, beside one they own staying put.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    mine = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, mine, None)
    theirs = Permanent(card=catalog_by_name["Hill Giant"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    change_control(mine, 1, source=catalog_by_name["Control Magic"], until_eot=False)
    game._sync_control()
    assert game.controller_index_of(mine) == 1

    alice.hand = [set_pool("USG")["Brand"]]
    game.cast_from_hand(0, "Brand")
    resolve_stack(game)

    assert game.controller_index_of(mine) == 0
    assert game.controller_index_of(theirs) == 1, "they own the Giant"


def test_brands_control_change_outlives_the_turn(set_pool, catalog_by_name):
    """"(This effect lasts indefinitely.)" restates CR 611.2a — an effect with
    no stated duration has no end — so the contribution must not be the
    until-end-of-turn one, which cleanup drops.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    mine = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, mine, None)
    change_control(mine, 1, source=catalog_by_name["Control Magic"], until_eot=False)
    game._sync_control()

    alice.hand = [set_pool("USG")["Brand"]]
    game.cast_from_hand(0, "Brand")
    resolve_stack(game)
    game.resolve_cleanup_step(0)

    assert game.controller_index_of(mine) == 0


# --- W3G1: Turnabout — a card type and a mode both chosen on resolution ---
import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar import parse_line
from engine.grammar.errors import GrammarError
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec

from tests.helpers import resolve_stack

#: What Turnabout offers. The list is the card's, not a catalog's — a seat that
#: could answer "enchantment" would name a type the sentence never printed.
_W3G1_OPTIONS = ["artifact", "creature", "land"]


def _w3g1_pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards([path]):
            pool.setdefault(card.name, card)
    return pool


def _w3g1_turnabout(set_pool, *, tapped: bool):
    """Seat 1 holds two Islands, a Grizzly Bears and a Black Lotus, all in the
    same tapped state; seat 0 holds a Turnabout and an Island of their own.

    The caster's own Island is what makes "target player controls" a real
    assertion rather than a coincidence: an untargeted sweep would move it too.
    """
    pool = _w3g1_pool()
    alice = PlayerState(
        name="A", hand=[set_pool("USG")["Turnabout"]],
        battlefield=[Permanent(card=pool["Island"])],
    )
    bob = PlayerState(name="B", battlefield=[
        Permanent(card=pool["Island"]), Permanent(card=pool["Island"]),
        Permanent(card=pool["Grizzly Bears"]), Permanent(card=pool["Black Lotus"]),
    ])
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    for permanent in bob.battlefield:
        permanent.tapped = tapped
    alice.battlefield[0].tapped = tapped
    game.interactive_seats = {0}
    return game, alice, bob


def _w3g1_resolve(game, card_type: str, mode_index: int):
    """Answer the two prompts Turnabout owes, in the order it asks them."""
    game.cast_from_hand(0, "Turnabout", target_player_index=1)
    assert [choice.kind for choice in game.pending_choices] == ["card_type_choice"]
    assert game.pending_choices[0].data["options"] == _W3G1_OPTIONS
    # Answering the first prompt arms the second — one resolution, two
    # decisions, in the order the two sentences are printed.
    assert game.confirm_card_type_choice(0, card_type)
    assert [choice.kind for choice in game.pending_choices] == ["mode_choice"]
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=mode_index)
    resolve_stack(game)


def test_w3g1_turnabout_untaps_the_chosen_type(set_pool):
    """The untap arm reaches the chosen type and nothing else."""
    game, alice, bob, = _w3g1_turnabout(set_pool, tapped=True)

    _w3g1_resolve(game, "land", mode_index=1)

    assert [p.tapped for p in bob.battlefield] == [False, False, True, True]
    # …and not the caster's own land, however tapped it is: the sweep is
    # scoped to the player the spell chose (CR 601.2c).
    assert alice.battlefield[0].tapped


def test_w3g1_turnabout_taps_the_chosen_type(set_pool):
    """The tap arm, over a different chosen type, on an untapped board."""
    game, alice, bob = _w3g1_turnabout(set_pool, tapped=False)

    _w3g1_resolve(game, "artifact", mode_index=0)

    # Only the Black Lotus is an artifact.
    assert [p.tapped for p in bob.battlefield] == [False, False, False, True]
    assert not alice.battlefield[0].tapped


def test_w3g1_turnabout_taps_creatures_when_creature_is_chosen(set_pool):
    """The type is payload, so the same two instructions cover all three
    options — this is the third one, and the one a Falter-style tap wants."""
    game, _alice, bob = _w3g1_turnabout(set_pool, tapped=False)

    _w3g1_resolve(game, "creature", mode_index=0)

    assert [p.tapped for p in bob.battlefield] == [False, False, True, False]


def test_w3g1_turnabout_offers_a_player_to_target(set_pool):
    """The picker offers what the sentence names, derived from the compiled
    program — the alternatives are nested inside a mode, and the seat has to
    survive that."""
    card = set_pool("USG")["Turnabout"]

    assert derive_cast_spec(card, compile_card_oracle(card)) == {"kind": "player"}


def test_w3g1_a_single_card_type_is_not_a_choice_sentence():
    """"Choose artifact, creature, or land" is a *list*; one word is a
    different sentence entirely and this production must not claim it."""
    with pytest.raises(GrammarError):
        parse_line("Choose artifact.")


def test_w3g1_a_comma_before_or_claims_only_what_the_line_already_refused():
    """The widened probe reads a comma in front of an alternative's "or".

    It is safe because a comma at that position is where the line fails today —
    so a sentence whose alternative cannot be parsed still fails, at the same
    place, rather than being half-read and silently dropped.
    """
    with pytest.raises(GrammarError):
        parse_line("Draw a card, or grokk the frumious bandersnatch.")

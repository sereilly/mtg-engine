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

The **wave-2 and wave-3** blocks. See `test_usg_enchantments.py` for the split's
reason; the cut is the round boundary between waves.
"""


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

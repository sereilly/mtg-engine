"""Invasion sorceries.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G7: piles ---
from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine import targeting as _w1g7_targeting
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import _mk_card as _w1g7_mk_card
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_body(name, power, toughness):
    """A vanilla creature permanent whose size is its name's business."""
    card = _w1g7_mk_card(name, "{2}", "Creature - Bear", "")
    card.raw.update({"power": str(power), "toughness": str(toughness)})
    w1g7_body_permanent = _W1G7Permanent(card=card)
    return w1g7_body_permanent


def _w1g7_table(set_pool, spell, *, mine=(), theirs=(), graveyard=(), interactive=()):
    """Seat 0 holding *spell* (an Invasion card), with the boards given."""
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", hand=[set_pool("INV")[spell]], battlefield=list(mine),
            graveyard=list(graveyard),
        ),
        _W1G7PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game._sync_control()
    game.interactive_seats = set(interactive)
    game.enforce_mana_costs = False
    game.start_turn(0)
    w1g7_spell_table = game
    return w1g7_spell_table


def _w1g7_board(game, seat):
    w1g7_board_names = [p.card.name for p in game.controlled_by(seat)]
    return w1g7_board_names


def _w1g7_owed(game):
    w1g7_owed_prompts = [(c.kind, c.player_index) for c in game.pending_choices]
    return w1g7_owed_prompts


def test_w1g7_do_or_die_the_caster_separates_and_the_victim_picks_the_pile_that_dies(set_pool):
    """"Separate all creatures target player controls into two piles. Destroy
    all creatures in the pile of that player's choice. They can't be
    regenerated."

    The caster separates (CR 608.2c — no subject is printed), the *targeted
    player* chooses, and the chosen pile is destroyed with no regeneration: the
    shield on the creature in it is not spent and does not save it. The other
    pile, the victim's land and the caster's own creature are untouched.
    """
    card = set_pool("INV")["Do or Die"]
    program = _w1g7_compile(card)
    assert program.supported, program.reason
    # "Target player" is announced (CR 601.2c), so the client is offered one.
    assert _w1g7_targeting.derive_cast_spec(card, program) == {"kind": "player"}

    shielded = _w1g7_body("Shielded", 2, 2)
    shielded.regeneration_shield += 1
    theirs = [
        shielded, _w1g7_body("Second", 3, 3), _w1g7_body("Third", 1, 1),
        _W1G7Permanent(card=set_pool("LEA")["Forest"]),
    ]
    game = _w1g7_table(
        set_pool, "Do or Die", mine=[_w1g7_body("Mine", 4, 4)], theirs=theirs,
        interactive=[0, 1],
    )
    assert game.cast_from_hand(0, "Do or Die", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_owed(game) == [("pile_split", 0)], "the caster separates"
    split = game.pending_choice_of("pile_split", 0)
    # Only the targeted player's creatures are in the piles — not their land,
    # not the caster's creature.
    assert len(split.data["_group"].items) == 3
    assert game.confirm_pile_split(0, [0, 2])
    assert _w1g7_owed(game) == [("pile_choice", 1)], "that player chooses"
    assert game.confirm_pile_choice(1, 0)

    assert _w1g7_board(game, 1) == ["Second", "Forest"], game.log
    assert sorted(c.name for c in game.players[1].graveyard) == ["Shielded", "Third"]
    assert _w1g7_board(game, 0) == ["Mine"]
    assert not game.stack and not game.pending_choices


def test_w1g7_do_or_die_headless_seats_split_evenly_and_keep_the_better_pile(set_pool):
    """Both decisions have a default that reads the board. The separator's is
    the most even split by value — a 5/5 against a 3/3 and a 1/1 here is not
    even, so the 5/5 stands alone against the other two — and the victim,
    choosing which of their own piles dies, gives up the lesser one."""
    theirs = [
        _w1g7_body("Giant", 6, 6), _w1g7_body("Middle", 2, 2),
        _w1g7_body("Runt", 1, 1),
    ]
    game = _w1g7_table(set_pool, "Do or Die", theirs=theirs)
    assert game.cast_from_hand(0, "Do or Die", target_player_index=1).supported
    _w1g7_resolve_stack(game)

    assert _w1g7_board(game, 1) == ["Giant"], game.log
    assert sorted(c.name for c in game.players[1].graveyard) == ["Middle", "Runt"]


def test_w1g7_death_or_glory_an_opponent_exiles_one_pile_and_the_other_returns(set_pool):
    """"Separate all creature cards in your graveyard into two piles. Exile the
    pile of an opponent's choice and return the other to the battlefield."

    The caster separates their own graveyard's **creature** cards — the
    instant among them is in neither pile and stays put — and the opponent
    chooses which pile is exiled. The two Grizzly Bears are one
    ``CardDefinition`` object, as two copies in a deck always are, and they go
    into different piles: one is exiled and one comes back, which only a
    graveyard *index* can say (CR 700.3c keeps the graveyard's order).
    """
    program = _w1g7_compile(set_pool("INV")["Death or Glory"])
    assert program.supported, program.reason

    lea = set_pool("LEA")
    graveyard = [
        lea["Shivan Dragon"], lea["Grizzly Bears"], lea["Lightning Bolt"],
        lea["Grizzly Bears"], lea["Serra Angel"],
    ]
    game = _w1g7_table(
        set_pool, "Death or Glory", graveyard=graveyard, interactive=[0, 1],
    )
    assert game.cast_from_hand(0, "Death or Glory").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_owed(game) == [("pile_split", 0)]
    split = game.pending_choice_of("pile_split", 0)
    assert split.data["_group"].items == [0, 1, 3, 4], "creature cards, by index"
    # Dragon and the first Bears against the second Bears and the Angel.
    assert game.confirm_pile_split(0, [0, 1])
    assert _w1g7_owed(game) == [("pile_choice", 1)], "an opponent chooses"
    assert game.confirm_pile_choice(1, 0)

    caster = game.players[0]
    assert sorted(c.name for c in caster.exile) == ["Grizzly Bears", "Shivan Dragon"]
    assert sorted(_w1g7_board(game, 0)) == ["Grizzly Bears", "Serra Angel"], game.log
    assert [c.name for c in caster.graveyard] == ["Lightning Bolt", "Death or Glory"]
    assert not game.stack and not game.pending_choices


def test_w1g7_death_or_glory_headless_the_opponent_exiles_the_better_pile(set_pool):
    """The opponent's default reads the piles and exiles the more valuable one
    — it is choosing *against* the player the cards belong to."""
    lea = set_pool("LEA")
    graveyard = [lea["Shivan Dragon"], lea["Grizzly Bears"], lea["Scryb Sprites"]]
    game = _w1g7_table(set_pool, "Death or Glory", graveyard=graveyard)
    assert game.cast_from_hand(0, "Death or Glory").supported
    _w1g7_resolve_stack(game)

    caster = game.players[0]
    assert [c.name for c in caster.exile] == ["Shivan Dragon"], game.log
    assert sorted(_w1g7_board(game, 0)) == ["Grizzly Bears", "Scryb Sprites"]


def test_w1g7_bend_or_break_every_player_separates_and_an_opponent_picks_what_is_destroyed(set_pool):
    """"Each player separates all nontoken lands they control into two piles.
    For each player, one of their piles is chosen by one of their opponents of
    their choice. Destroy all lands in the chosen piles. Tap all lands in the
    other piles."

    Four decisions at two seats, in APNAP order (CR 101.4, CR 608.2e): both
    separations first, then both choices — each made by the *other* player —
    and only then do the fates happen, over both players' piles at once. A
    creature is in nobody's pile.
    """
    program = _w1g7_compile(set_pool("INV")["Bend or Break"])
    assert program.supported, program.reason

    lea = set_pool("LEA")

    def lands(*names):
        w1g7_lands = [_W1G7Permanent(card=lea[name]) for name in names]
        return w1g7_lands

    game = _w1g7_table(
        set_pool, "Bend or Break",
        mine=lands("Forest", "Mountain", "Plains"),
        theirs=lands("Island", "Swamp") + [_w1g7_body("Bystander", 2, 2)],
        interactive=[0, 1],
    )
    assert game.cast_from_hand(0, "Bend or Break").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_owed(game) == [("pile_split", 0)], "the active player separates first"
    assert game.confirm_pile_split(0, [0])
    assert _w1g7_owed(game) == [("pile_split", 1)]
    assert len(game.pending_choices[0].data["_group"].items) == 2, "lands only"
    assert game.confirm_pile_split(1, [0, 1])
    # Nothing has happened to any land yet: every choice comes first.
    assert all(not p.tapped for p in game.all_permanents())
    assert _w1g7_owed(game) == [("pile_choice", 1)], "P2 chooses between P1's piles"
    assert game.confirm_pile_choice(1, 1)
    assert _w1g7_owed(game) == [("pile_choice", 0)], "P1 chooses between P2's piles"
    # P2 put both lands in one pile; P1 picks the empty one, so nothing of
    # P2's is destroyed and both are tapped.
    assert game.confirm_pile_choice(0, 1)

    assert [(p.card.name, p.tapped) for p in game.controlled_by(0)] == [
        ("Forest", True),
    ], game.log
    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Bend or Break", "Mountain", "Plains",
    ]
    assert [(p.card.name, p.tapped) for p in game.controlled_by(1)] == [
        ("Island", True), ("Swamp", True), ("Bystander", False),
    ]
    assert not game.stack and not game.pending_choices


def test_w1g7_bend_or_break_headless_everyone_loses_about_half(set_pool):
    """Headless, every separator splits as evenly as it can and every chooser
    — choosing against the lands' owner — destroys the bigger pile."""
    lea = set_pool("LEA")
    mine = [_W1G7Permanent(card=lea["Forest"]) for _ in range(3)]
    theirs = [_W1G7Permanent(card=lea["Island"]) for _ in range(4)]
    game = _w1g7_table(set_pool, "Bend or Break", mine=mine, theirs=theirs)
    assert game.cast_from_hand(0, "Bend or Break").supported
    _w1g7_resolve_stack(game)

    assert [(p.card.name, p.tapped) for p in game.controlled_by(0)] == [("Forest", True)]
    assert [(p.card.name, p.tapped) for p in game.controlled_by(1)] == [
        ("Island", True), ("Island", True),
    ], game.log


def _w1g7_sized_card(name, type_line, mana_value):
    """A card with a stated mana value and no text."""
    from engine.models import CardDefinition

    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update({"power": "2", "toughness": "2"})
    w1g7_sized = CardDefinition(
        name=name, mana_cost="{%d}" % mana_value if mana_value else "",
        cmc=float(mana_value), type_line=type_line, oracle_text="", colors=(),
        color_identity=(), keywords=(), produced_mana=(), raw=raw,
    )
    return w1g7_sized


def test_w1g7_desperate_research_takes_every_copy_of_the_named_card_and_exiles_the_rest(set_pool):
    """"Choose a card name other than a basic land card name. Reveal the top
    seven cards of your library and put all of them with that name into your
    hand. Exile the rest."

    The name is chosen first and the printed bound on it is enforced where the
    choice is made: a basic land's name — plain, snow-covered or Wastes — is
    refused, not repaired. Both Shivan Dragons among the top seven go to the
    hand, the other five are **exiled** (not binned), and the eighth card never
    moves.
    """
    program = _w1g7_compile(set_pool("INV")["Desperate Research"])
    assert program.supported, program.reason

    lea = set_pool("LEA")
    library = [
        lea[name] for name in (
            "Forest", "Shivan Dragon", "Lightning Bolt", "Shivan Dragon", "Island",
            "Forest", "Serra Angel", "Mountain",
        )
    ]
    game = _w1g7_table(set_pool, "Desperate Research", interactive=[0])
    game.players[0].library = library
    assert game.cast_from_hand(0, "Desperate Research").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    prompt = game.pending_choice_of("choose_card_name", 0)
    assert prompt is not None and prompt.data.get("exclude_basic_land_names")
    assert len(game.players[0].library) == 8, "nothing is revealed before the name"
    for refused in ("Forest", "island", "Snow-Covered Mountain", "Wastes"):
        assert not game.confirm_choose_card_name(0, refused), refused
    assert game.confirm_choose_card_name(0, "Shivan Dragon")

    caster = game.players[0]
    assert [c.name for c in caster.hand] == ["Shivan Dragon", "Shivan Dragon"]
    assert [c.name for c in caster.exile] == [
        "Forest", "Lightning Bolt", "Island", "Forest", "Serra Angel",
    ]
    assert [c.name for c in caster.graveyard] == ["Desperate Research"]
    assert [c.name for c in caster.library] == ["Mountain"]
    assert not game.stack and not game.pending_choices


def test_w1g7_void_destroys_and_discards_by_the_number_its_caster_names(set_pool):
    """"Choose a number. Destroy all artifacts and creatures with mana value
    equal to that number. Then target player reveals their hand and discards
    all nonland cards with mana value equal to the number."

    A *spell* choosing a number, with no printed bound (CR 107.1: any whole
    number from zero up — a negative one is refused). Naming three takes every
    artifact and creature of mana value three **on both sides**, leaves the
    enchantment of the same mana value and the two-drops, and then strips the
    targeted hand of its nonland threes.
    """
    card = set_pool("INV")["Void"]
    program = _w1g7_compile(card)
    assert program.supported, program.reason
    assert _w1g7_targeting.derive_cast_spec(card, program) == {"kind": "player"}

    three = _w1g7_sized_card("Three Drop", "Creature - Bear", 3)
    rock = _w1g7_sized_card("Three Rock", "Artifact", 3)
    aura = _w1g7_sized_card("Three Glyph", "Enchantment", 3)
    two = _w1g7_sized_card("Two Drop", "Creature - Bear", 2)
    spell3 = _w1g7_sized_card("Three Spell", "Sorcery", 3)
    spell1 = _w1g7_sized_card("One Spell", "Instant", 1)
    forest = set_pool("LEA")["Forest"]
    game = _w1g7_table(
        set_pool, "Void",
        mine=[_W1G7Permanent(card=three), _W1G7Permanent(card=two)],
        theirs=[
            _W1G7Permanent(card=three), _W1G7Permanent(card=rock),
            _W1G7Permanent(card=aura), _W1G7Permanent(card=two),
            _W1G7Permanent(card=forest),
        ],
        interactive=[0],
    )
    game.players[1].hand = [spell3, spell1, three, forest]
    assert game.cast_from_hand(0, "Void", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    prompt = game.pending_choice_of("number_choice", 0)
    assert prompt is not None
    assert (prompt.data["minimum"], prompt.data["maximum"]) == (0, None)
    assert not game.confirm_number_choice(0, -1)
    assert game.confirm_number_choice(0, 3)

    assert _w1g7_board(game, 0) == ["Two Drop"], game.log
    assert _w1g7_board(game, 1) == ["Three Glyph", "Two Drop", "Forest"]
    victim = game.players[1]
    assert [c.name for c in victim.hand] == ["One Spell", "Forest"]
    assert sorted(c.name for c in victim.graveyard) == [
        "Three Drop", "Three Drop", "Three Rock", "Three Spell",
    ]
    assert any("Void: chose 3" in line for line in game.log)
    assert not game.stack and not game.pending_choices


def test_w1g7_void_naming_zero_spares_lands_on_the_board_and_in_the_hand(set_pool):
    """Zero is a number, and the two sentences each say what it does not
    reach: a land is neither an artifact nor a creature, and the discard is of
    **nonland** cards — so naming zero on a board of lands takes nothing."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g7_table(
        set_pool, "Void", theirs=[_W1G7Permanent(card=forest)], interactive=[0],
    )
    game.players[1].hand = [forest, _w1g7_sized_card("One Spell", "Instant", 1)]
    game.cast_from_hand(0, "Void", target_player_index=1)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_number_choice(0, 0)

    assert _w1g7_board(game, 1) == ["Forest"]
    assert [c.name for c in game.players[1].hand] == ["Forest", "One Spell"]


def test_w1g7_void_headless_names_the_number_that_costs_the_opponent_most(set_pool):
    """A seat that is not asked names the mana value borne by the most
    permanents its opponents control, net of its own — read off the
    battlefield, which is public, and never off a hand."""
    three = _w1g7_sized_card("Three Drop", "Creature - Bear", 3)
    two = _w1g7_sized_card("Two Drop", "Creature - Bear", 2)
    game = _w1g7_table(
        set_pool, "Void",
        mine=[_W1G7Permanent(card=two), _W1G7Permanent(card=two)],
        theirs=[
            _W1G7Permanent(card=three), _W1G7Permanent(card=three),
            _W1G7Permanent(card=two),
        ],
    )
    game.cast_from_hand(0, "Void", target_player_index=1)
    _w1g7_resolve_stack(game)
    # The number is a queued prompt for every seat; a headless table drains it
    # the way the simulator does, and the steps behind it then run.
    game.auto_resolve_pending_choices()

    assert _w1g7_board(game, 1) == ["Two Drop"], game.log
    assert _w1g7_board(game, 0) == ["Two Drop", "Two Drop"]

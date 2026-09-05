"""Visions creatures.

Opened at the set's ingest with the yield of Phase 1's suite run — see
SET_PLAYBOOK.md, "treat what fires as yield, not noise".
"""

from engine.oracle import compile_card_oracle


def test_kyscu_drake_charges_both_halves_of_its_conjoined_sacrifice(set_pool):
    """"Sacrifice this creature **and a creature named Spitting Drake**".

    Two objects under one printed verb, joined by a bare "and" with no comma —
    the shape every reader in the charger declined. The Oxford-list regex needs
    a comma before its "and", the single-object delimiter is switched off once
    "sacrifice this ..." has set ``sacrifice_self``, and the "any number of"
    reader wants a set. So the Drake's own sacrifice was charged and the second
    creature was not: an ability activated for less than the card prints, which
    is the failure that neither crashes nor goes missing.
    """
    drake = set_pool("VIS")["Kyscu Drake"]
    program = compile_card_oracle(drake)

    tutor = [
        ability
        for ability in program.activated_abilities
        if ability.cost.sacrifice_self
    ]
    assert len(tutor) == 1, "the tutor ability is the one that sacrifices itself"
    cost = tutor[0].cost

    # The source in its flag and the chosen permanent in the filter — the same
    # encoding the Oxford-list path already gives the same two facts.
    assert cost.sacrifice_self is True
    assert cost.sacrifice_filter == {
        "type_filter": "creature",
        "named": "spitting drake",
    }


# --- W1G5: the library, the graveyard and a counter read at death ---

from engine import Game as _G5Game, PlayerState as _G5PlayerState
from engine.models import Permanent as _G5Permanent
from engine.named_counters import counters_on as _g5_counters_on
from engine.oracle import compile_card_oracle as _g5_compile


def _g5_game(players):
    game = _G5Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    return game


def test_goblin_recruiter_searches_for_any_number_of_goblins(set_pool):
    """"Search your library for **any number of** Goblin cards, reveal them,
    then shuffle and put those cards on top in any order."

    Two gaps, both in the *parse*: the search production had no reading for a
    count with no printed ceiling ("a search for more than one card has no
    representation"), and the counted spelling had no reading for the
    top-of-library tail the singular one has carried since the three Mirage
    tutors.

    The ceiling is the zone rather than the card, so the count travels as the
    printed word and the handler resolves it against the library — a number in
    the payload would be a ceiling this card does not print.
    """
    vis, mir, lea = set_pool("VIS"), set_pool("MIR"), set_pool("LEA")
    program = _g5_compile(vis["Goblin Recruiter"])
    assert program.supported, program.reason
    assert program.instructions[0].payload == {
        "count": "any", "card_type": "creature", "up_to": True, "reveal": True,
        "restrictions": {"subtypes": ["goblin"]}, "destination": "library_top",
    }

    goblins = [mir["Goblin Elite Infantry"], mir["Goblin Tinkerer"]]
    library = [lea["Island"], goblins[0], lea["Mountain"], goblins[1]]
    game = _g5_game([
        _G5PlayerState(name="P1", hand=[vis["Goblin Recruiter"]], library=list(library)),
        _G5PlayerState(name="P2", library=[lea["Island"]] * 6),
    ])
    game.interactive_seats = {0}

    assert game.cast_from_hand(0, "Goblin Recruiter").supported
    game.resolve_stack()

    prompt = game.pending_search_library
    # The count is the number of matching cards in the library, not a printed
    # ceiling — and "up to" rides with it, so finding fewer stays legal.
    assert prompt["count"] == 2
    assert prompt["up_to"] is True

    picks = [
        {"zone": "library", "index": index}
        for index, card in enumerate(game.players[0].library)
        if card in goblins
    ]
    assert game.confirm_search_library_picks(0, picks)

    # "…on top **in any order**": the finder named them in the order they want,
    # and the first one named is the first from the top. Nothing went to hand —
    # the counted placement had no `library_top` branch at all before this, and
    # every find fell through to the finder's hand, which is a different card.
    assert [c.name for c in game.players[0].library][:2] == [
        goblins[0].name, goblins[1].name,
    ]
    assert game.players[0].hand == []


def test_bogardan_phoenix_comes_back_once_and_then_is_exiled(set_pool):
    """"When this creature dies, exile it if it had a death counter on it.
    Otherwise, return it to the battlefield under your control and put a death
    counter on it."

    Four separate things were missing and only a game finds the last three: the
    named-counter clause had no parse; the counter landed on the **dead**
    permanent rather than on the one the return had just made (CR 400.7), so the
    store read zero and the Phoenix returned for ever; the self-dies fire site
    froze no counters at all, so the condition could never answer True; and
    ``exile_self`` looked only on the battlefield, so the exile branch logged
    "nothing to exile" and left the card in the graveyard.
    """
    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = _g5_compile(vis["Bogardan Phoenix"])
    assert program.supported, program.reason
    branch = program.triggered_abilities[0].instruction
    assert branch.payload["condition"] == {
        "kind": "had_named_counter", "counter": "death",
    }

    phoenix = _G5Permanent(card=vis["Bogardan Phoenix"])
    game = _g5_game([
        _G5PlayerState(
            name="P1", battlefield=[phoenix],
            hand=[lea["Lightning Bolt"]] * 2, library=[lea["Island"]] * 6,
        ),
        _G5PlayerState(name="P2", library=[lea["Island"]] * 6),
    ])

    def bolt(victim):
        game.cast_from_hand(
            0, "Lightning Bolt", target_player_index=0,
            target_permanent_index=game.battlefield_index_of(victim),
        )
        game.resolve_stack()
        game._settle()
        game.resolve_stack()

    bolt(phoenix)
    returned = list(game.controlled_by(game.players[0]))
    assert [p.card.name for p in returned] == ["Bogardan Phoenix"]
    # The counter is on the permanent the *return* made, not on the object that
    # died: CR 400.7 makes them different objects.
    assert _g5_counters_on(returned[0], "death") == 1

    bolt(returned[0])
    assert list(game.controlled_by(game.players[0])) == []
    assert [c.name for c in game.players[0].exile] == ["Bogardan Phoenix"]
    assert "Bogardan Phoenix" not in [c.name for c in game.players[0].graveyard]


def test_guiding_spirit_moves_only_a_creature_card(set_pool):
    """"{T}: If the top card of target player's graveyard is a creature card,
    put that card on top of that player's library."

    The printed "if" is part of the effect rather than a condition over it:
    both halves name the top card of one graveyard, and split apart neither
    half can say which card it means. So one production reads the whole
    sentence, and the filter rides the payload.
    """
    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = _g5_compile(vis["Guiding Spirit"])
    assert program.supported, program.reason
    move = program.activated_abilities[0]
    assert move.instruction.kind == "graveyard_top_to_library"
    assert move.instruction.payload["filter"] == {"type_filter": "creature"}

    def rig(top):
        spirit = _G5Permanent(card=vis["Guiding Spirit"])
        game = _g5_game([
            _G5PlayerState(name="P1", battlefield=[spirit], library=[lea["Island"]] * 4),
            _G5PlayerState(
                name="P2", library=[lea["Island"]] * 4,
                graveyard=[lea["Black Lotus"], top],
            ),
        ])
        spirit.metadata["summoning_sickness_turn"] = -99
        return game

    # The **top** of a graveyard is the last card put into it, which this engine
    # keeps as the end of the list. Reading it the other way round moves the
    # oldest card in the pile, which plays and is wrong.
    game = rig(lea["Grizzly Bears"])
    assert game.activate_permanent_ability(
        0, "Guiding Spirit", target_player_index=1,
    ).supported
    game.resolve_stack()
    assert game.players[1].library[0].name == "Grizzly Bears"
    assert [c.name for c in game.players[1].graveyard] == ["Black Lotus"]

    game = rig(lea["Mountain"])
    game.activate_permanent_ability(0, "Guiding Spirit", target_player_index=1)
    game.resolve_stack()
    assert game.players[1].library[0].name == "Island"
    assert [c.name for c in game.players[1].graveyard] == ["Black Lotus", "Mountain"]

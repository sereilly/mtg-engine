"""Every count of cards **by name** in a zone, across the pool (CR 201.2a).

ODY W1G4 changed the one name test every zone count asks
(``handlers/_filters._card_matches_filter``): it reads a card's *set* of names
now (CR 709.4a: a split card has two) and it can be told which spell's effect
is asking, because a card in a graveyard may count as a card of another name to
exactly that spell — "If this card is in a graveyard, effects from spells named
Flame Burst count it as a card named Flame Burst" (Pardic Firecat, Diligent
Farmhand; ``engine/counted_names.py``).

Neither is visible to ``oracle_diff``: no compiled program moved. So this is
the census the change owes — every compiled count in both manifest roles that
narrows a card zone by a printed name, evaluated against one graveyard built to
show each way the test could go wrong.
"""

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.handlers._amounts import evaluate_count
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from tests.helpers import _mk_card

#: A count spec is any dict carrying a zone and a filter — found wherever a
#: payload nests one (``x_from_count``, ``per_each``, ``count_spec``, a
#: condition's count), so a new channel is examined without being listed here.
def _named_zone_specs(value, found):
    if isinstance(value, OracleInstruction):
        _named_zone_specs(value.payload, found)
    elif isinstance(value, dict):
        described = value.get("filter")
        if (
            isinstance(described, dict) and described.get("named")
            and value.get("zone") not in (None, "battlefield")
        ):
            found.append(value)
        for nested in value.values():
            _named_zone_specs(nested, found)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _named_zone_specs(nested, found)


def _both_roles():
    seen = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            seen.setdefault(card.name, card)
    return list(seen.values())


def _population():
    rows = []
    for unit in compilation_units(_both_roles()):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        found: list = []
        _named_zone_specs(program.instructions, found)
        for ability in program.activated_abilities:
            _named_zone_specs(ability.instruction, found)
        for trigger in program.triggered_abilities:
            _named_zone_specs(trigger.instruction, found)
        rows.extend((unit, spec) for spec in found)
    return rows


def test_every_named_zone_count_counts_the_cards_of_that_name_and_no_other():
    rows = _population()
    # Kindle, Accumulated Knowledge and the five Bursts at the least. A floor,
    # because a walker that stopped finding specs would pass over an empty set.
    assert len(rows) >= 7, [card.name for card, _spec in rows]

    pool = {card.name: card for card in _both_roles()}
    wrong = []
    for card, spec in rows:
        named = str(spec["filter"]["named"])
        zone = spec["zone"]
        # The name as the *card* spells it: the spec holds the grammar's
        # lower-cased rendering, and the cards that print these counts count
        # their own name.
        real = next(
            (c for c in pool.values() if c.name.lower() == named.lower()), card
        )
        helper = _mk_card(
            "Census Helper", "{1}", "Creature — Test",
            f"If this card is in a graveyard, effects from spells named "
            f"{real.name} count it as a card named {real.name}.",
        )
        stranger = _mk_card(
            "Census Stranger", "{1}", "Creature — Test",
            "If this card is in a graveyard, effects from spells named "
            "Census Elsewhere count it as a card named Census Elsewhere.",
        )
        pile = [real, real, pool["Grizzly Bears"], pool["Fire // Ice"], helper, stranger]
        seats = [PlayerState(name="A", life=20), PlayerState(name="B", life=20)]
        setattr(seats[0], zone, list(pile[:3]))
        setattr(seats[1], zone, list(pile[3:]))
        game = Game(players=seats)
        scoped = dict(spec, owner="all")
        expected = {
            # Nobody's effect: CR 201.2a and nothing more.
            None: 2,
            # The named spell's effect, in a graveyard: the helper is one more
            # card — one, however many lines it prints — and the stranger, who
            # counts for some other spell, is not.
            real.name: 3 if zone == "graveyard" else 2,
            # Another spell's effect.
            "Census Elsewhere": 2,
        }
        for asking, want in expected.items():
            base = {k: v for k, v in scoped.items()
                    if k not in ("plus", "multiplier", "offset", "half", "as_cast")}
            got = evaluate_count(game, seats[0], base, effect_spell=asking)
            if got != want:
                wrong.append((card.name, named, zone, asking, got, want))
    assert not wrong, wrong


def test_a_split_card_in_a_zone_is_counted_under_either_half_name():
    """CR 709.4a. The name test read the whole card's printed spelling
    ("Fire // Ice"), which is neither of its names."""
    pool = {card.name: card for card in _both_roles()}
    seats = [
        PlayerState(name="A", life=20, graveyard=[pool["Fire // Ice"], pool["Grizzly Bears"]]),
        PlayerState(name="B", life=20, graveyard=[pool["Fire // Ice"]]),
    ]
    game = Game(players=seats)
    for half in ("fire", "ice"):
        spec = {"zone": "graveyard", "owner": "all", "filter": {"named": half}}
        assert evaluate_count(game, seats[0], spec) == 2, half
    spec = {"zone": "graveyard", "owner": "all", "filter": {"named": "fire // ice"}}
    assert evaluate_count(game, seats[0], spec) == 0

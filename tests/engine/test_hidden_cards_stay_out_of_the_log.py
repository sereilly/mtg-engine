"""Census: ``game.log`` never names a card no opponent may see (CR 400.2,
406.3, 708.5).

``game.log`` is one list, served whole to every seat and every spectator
(``engine/refusals.py``), so a line in it is an announcement. Three kinds of
card are hidden from the table, and a line naming one gives it away:

* a card in a **hand** or a **library** (CR 400.2) that nothing revealed;
* a card **exiled face down** (CR 406.3), hidden from every player, its owner
  included, unless an instruction lets one of them look — and a permission to
  look is one seat's view, never the table's;
* the card behind a **face-down permanent or spell** (CR 708.5).

``tests/engine/test_private_finds_stay_out_of_the_log.py`` holds the private
look and the private search. This census holds everything else: it drives
**every** supported card in both manifest roles whose compiled program moves a
card through a hidden zone or exiles one face down (any step whose kind names a
library, a hand, an exile, a look, a search, a shuffle, a pile, the top or
bottom, a reveal, a face, morph or the outside of the game — or carries
``face_down``), and every supported card that can aim at a face-down
creature, aimed at one. Each is driven through the entry point its own text
gives it, then through its controller's end step and to its next upkeep (so a
delayed "put that card into your hand" — Necropotence, Three Wishes — fires).

The table: both libraries and both hands are cards with names nothing else on
the table says, and each battlefield holds a face-down creature whose card is
just as distinct. ``game.log`` is replaced by a list that, on **every**
append, asks of every such name in the line whether that card is hidden right
now — in a hand, a library, a face-down exile, or behind a face-down object —
and was never seen in a public zone. A line that says "reveal" is the reveal
itself (Brass Herald, Fact or Fiction), and a card it names is public from
then on. A card whose own text prints "reveal" or names a card is excused, as
the private-find census excuses it: its search or its pick is announced.

Validated backwards (``scratch/scg/w2g4``). With W1G7's three hunks reverted
(``exile_top_of_library``'s face-down count, the face-down pile search line,
``put_exiled_pile_top_into_hand``) the movers census names exactly W1G7's
seven: Mangara's Tome, Parallel Thoughts, Necropotence, Knowledge Vault,
Duplicity, Kyren Archive and Three Wishes. On W2G4's base engine it named
seven more rows: Gustha's Scepter's exile and its look, Three Wishes' look and
play permissions, Necropotence's end-step "put X into their hand from exile",
Painful and Agonizing Memories' "went on top of", Phyrexian Portal's find, and
Sylvan Library's choice and its put-back. Kyren Archive's and Knowledge
Vault's "X go to their owner's hand" hid behind a second defect the census
cannot see by name — the pile read face *up* once its exiler was sacrificed —
and ``tests/regressions/test_scg_w2g4_face_down_exile.py`` holds that one, with
the exiled cards' own upkeep triggers firing from exile. The aimed census read
nothing on the base engine: no log line names a face-down creature's card.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.face_down import face_down_card, hidden_card
from engine.faces import compilation_units
from engine.linked_exile import face_down_exiled_cards
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import OracleInstruction
from engine.targeting import derive_activation_spec, derive_cast_spec
from tests.helpers import _nosick, full_census, stable_sample, settle

#: A step whose kind names one of these moves a card through a hidden zone, or
#: exiles one, or turns one face down — the population, read off the program.
_HIDDEN_KINDS = re.compile(
    r"library|hand|exile|look|search|shuffle|face|morph|pile|top|bottom"
    r"|reveal|outside|wish"
)
#: Kinds the pattern catches that name no card: a draw says how many (the draw
#: seam's lines), and "counter the top spell" is about the stack.
_NAMES_NO_CARD = frozenset({
    "draw_controller_cards", "draw_target_cards", "counter_top_stack_spell",
})

# The table. Every name is a card nothing else on the census board — no rule
# text, prompt, or other log line — would say.
_LIBRARY = (
    ("Serra Angel", "Black Lotus", "Crusade", "Savannah Lions", "Juggernaut",
     "Tundra", "Swords to Plowshares", "Wrath of God", "Shivan Dragon",
     "Glasses of Urza"),
    ("Mahamoti Djinn", "Mox Pearl", "Bad Moon", "Wall of Stone", "Sol Ring",
     "Badlands", "Lightning Bolt", "Armageddon", "Craw Wurm", "Howling Mine"),
)
_HAND = (
    ("Hurloon Minotaur", "Ornithopter", "Giant Growth", "Scrubland", "Unsummon"),
    ("Gray Ogre", "Jade Statue", "Holy Strength", "Taiga", "Disintegrate"),
)
#: The card behind each seat's face-down creature (CR 708.5).
_FACE_DOWN = ("Exalted Angel", "Krosan Colossus")
_SECRETS = tuple(
    name for group in (*_LIBRARY, *_HAND, _FACE_DOWN) for name in group
)

#: Each secret as a whole name: "Crusade" is not said by a line about
#: Zhalfirin Crusader.
_SAYS = {
    name: re.compile(rf"(?<![\w']){re.escape(name)}(?![\w'])") for name in _SECRETS
}

#: Words in a card's own text that announce what its effect picks.
_ANNOUNCED = ("reveal", "name a card", "choose a card name")


def _pool() -> list:
    return list(compilation_units(load_cards(manifest_set_paths(include_measured=True))))


@pytest.fixture(scope="module")
def pool():
    return _pool()


@pytest.fixture(scope="module")
def by_name(pool):
    names: dict = {}
    for card in pool:
        names.setdefault(card.name, card)
    return names


def _walk(value):
    if isinstance(value, OracleInstruction):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _walk(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _walk(inner)


def _moves_hidden(instruction) -> bool:
    return any(
        step.kind not in _NAMES_NO_CARD
        and (_HIDDEN_KINDS.search(step.kind) or (step.payload or {}).get("face_down"))
        for step in _walk(instruction)
    )


def hidden_movers(pool) -> list[tuple]:
    """``(card, shape, ability index)`` for every supported card's spell,
    activated ability or trigger that moves a card through a hidden zone."""
    rows = []
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if card.primary_type in ("instant", "sorcery") and _moves_hidden(
            list(program.instructions)
        ):
            rows.append((card, "spell", None))
        for index, ability in enumerate(program.activated_abilities):
            if _moves_hidden(ability.instruction):
                rows.append((card, "activated", index))
        for index, trigger in enumerate(program.triggered_abilities):
            if _moves_hidden(trigger.instruction):
                rows.append((card, f"trigger:{trigger.condition.kind}", index))
    return rows


def aimers(pool) -> list[tuple]:
    """``(card, shape, ability index)`` for every supported spell and activated
    ability that could be aimed at a face-down creature: whatever ``targeting``
    derives a choice for, and whatever prints "target" (``legality.py``'s text
    fallback reaches some the derivation does not)."""
    rows = []
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        prints_target = "target" in (card.oracle_text or "").lower()
        if card.primary_type in ("instant", "sorcery") and (
            prints_target or derive_cast_spec(card, program) is not None
        ):
            rows.append((card, "spell", None))
        for index, ability in enumerate(program.activated_abilities):
            if prints_target or derive_activation_spec(ability) is not None:
                rows.append((card, "activated", index))
    return rows


def _hidden_now(game, name: str) -> str | None:
    """Where the card called *name* is hidden from somebody right now, or None
    when it is anywhere public (a graveyard, face up on the battlefield, the
    stack or exile) or nowhere."""
    where = None
    for seat, player in enumerate(game.players):
        if any(card.name == name for card in player.graveyard):
            return None
        if where is None and any(card.name == name for card in player.library):
            where = f"seat {seat}'s library"
        if where is None and any(card.name == name for card in player.hand):
            where = f"seat {seat}'s hand"
        face_down = face_down_exiled_cards(game, seat)
        for card in player.exile:
            if card.name != name:
                continue
            if not any(held is card for held in face_down):
                return None
            where = where or f"seat {seat}'s exile, face down"
    for permanent in game.all_permanents():
        behind = hidden_card(permanent.card)
        if behind is not None and behind.name == name:
            where = where or "a face-down permanent"
        elif permanent.card.name == name:
            return None
    for item in game.stack:
        behind = hidden_card(item.card)
        if behind is not None and behind.name == name:
            where = where or "a face-down spell"
        elif getattr(item.card, "name", None) == name:
            return None
    return where


def _anywhere(game, name: str) -> bool:
    for player in game.players:
        for zone in (player.library, player.hand, player.exile, player.graveyard):
            if any(card.name == name for card in zone):
                return True
    return any(p.card.name == name for p in game.all_permanents()) or any(
        getattr(item.card, "name", None) == name for item in game.stack
    )


class _WatchedLog(list):
    """``game.log``, asking on every line whether it names a hidden card.

    A line naming a card that is hidden as it is written is held until the
    next line (or the end of the drive), and counts only if the card is hidden
    still: a line written just before the move it describes ("… is put into
    its owner's graveyard") names a card on its way somewhere public. A card
    that is public now and then was seen, and its name is the table's
    afterwards — whatever hidden zone it goes to later."""

    def __init__(self, game, lines=()):
        super().__init__(lines)
        self.game = game
        self.seen_public: set[str] = set()
        self.held: list[tuple[str, str, str]] = []
        self.named: list[tuple[str, str, str]] = []

    def confirm(self) -> None:
        """Count every held line whose card is still hidden."""
        for line, name, where in self.held:
            if _hidden_now(self.game, name) is not None:
                self.named.append((line, name, where))
        self.held = []

    def append(self, line) -> None:
        super().append(line)
        self.confirm()
        text = str(line)
        for name in _SECRETS:
            if name not in self.seen_public and _hidden_now(self.game, name) is None                     and _anywhere(self.game, name):
                self.seen_public.add(name)
        for name in _SECRETS:
            if name in self.seen_public or not _SAYS[name].search(text):
                continue
            if "reveal" in text.lower():
                self.seen_public.add(name)
                continue
            where = _hidden_now(self.game, name)
            if where is not None:
                self.held.append((text, name, where))

    def extend(self, lines) -> None:
        for line in lines:
            self.append(line)


def _table(by_name, *, on_board=(), in_hand=()) -> tuple[Game, dict]:
    lands = [_nosick(Permanent(card=by_name[name]))
             for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]
    bears = _nosick(Permanent(card=by_name["Grizzly Bears"]))
    masks = [_nosick(Permanent(card=face_down_card(by_name[name]))) for name in _FACE_DOWN]
    game = Game(players=[
        PlayerState(
            name="Looker",
            battlefield=lands + [bears, masks[0]]
            + [_nosick(Permanent(card=card)) for card in on_board],
            library=[by_name[name] for name in _LIBRARY[0]],
            hand=[by_name[name] for name in _HAND[0]] + list(in_hand),
            graveyard=[by_name["Hill Giant"]],
        ),
        PlayerState(
            name="Other",
            battlefield=[_nosick(Permanent(card=by_name["Hill Giant"])), masks[1]],
            library=[by_name[name] for name in _LIBRARY[1]],
            hand=[by_name[name] for name in _HAND[1]],
        ),
    ])
    game.enforce_mana_costs = False
    game.log = _WatchedLog(game, game.log)
    return game, {"bears": bears, "mask": masks[1]}


def _aimed(game, entries, aim) -> dict:
    """The target arguments naming *aim* (a permanent) if the picker offers
    it, else seat 1, else the picker's first entry."""
    if aim is not None:
        for entry in entries:
            if entry.get("kind") == "permanent" and game.permanent_at(
                entry["seat"], entry["index"]
            ) is aim:
                return {"target_permanent_ids": [aim.permanent_id]}
    first = next(
        (e for e in entries if e.get("kind") == "player" and e["seat"] == 1),
        entries[0] if entries else None,
    )
    if first is None:
        return {}
    if first.get("kind") == "player":
        return {"target_player_index": first["seat"]}
    if first.get("kind") == "permanent":
        return {"target_permanent_ids": [
            game.permanent_at(first["seat"], first["index"]).permanent_id
        ]}
    return {}


def drive(by_name, card, shape, index, *, aim_at_mask=False) -> Game | None:
    """Run *card*'s *shape* for seat 0 with every answer defaulted, then its
    controller's end step and the turn round to its next upkeep. None when the
    card could not be driven."""
    is_spell = card.primary_type in ("instant", "sorcery")
    from_hand = shape == "activated" and "discard this card" in (card.oracle_text or "").lower()
    on_board = not is_spell and not from_hand and (
        shape == "activated" or shape.startswith("trigger:upkeep")
    )
    game, held = _table(
        by_name, on_board=[card] if on_board else (), in_hand=() if on_board else [card],
    )
    aim = held["mask"] if aim_at_mask else None
    game.start_turn(0)
    settle(game)
    if on_board and shape == "activated":
        slot = next(
            (i for i, p in enumerate(game.players[0].battlefield) if p.card is card), None,
        )
        if slot is None:
            # It did not survive its own first upkeep (Parallax Wave's fading,
            # with no counters on a permanent put straight onto the board).
            return None
        spec = game.activation_target_spec(0, slot, index)
        aimed = _aimed(game, spec.get("valid_targets") or [], aim) if spec.get(
            "requires_target"
        ) else {}
        if aim is not None and aimed.get("target_permanent_ids") != [aim.permanent_id]:
            return None
        result = game.activate_permanent_ability(0, card.name, ability_index=index, **aimed)
        if not result.supported:
            result = game.activate_permanent_ability(
                0, card.name, ability_index=index, target_player_index=1,
                cost_permanent_ids=[held["bears"].permanent_id], **{
                    k: v for k, v in aimed.items() if k != "target_player_index"
                },
            )
        if not result.supported:
            return None
    elif on_board:
        # An upkeep trigger: the turn after next is this seat's again.
        game.start_next_turn()
        settle(game)
        game.start_next_turn()
    elif shape == "activated":
        if not game.activate_from_hand(0, card.name).supported:
            return None
    else:
        spec = game.cast_target_spec(0, card)
        entries = spec.get("valid_targets") or []
        aimed = _aimed(game, entries, aim) if spec.get("requires_target") else {}
        if aim is not None and aimed.get("target_permanent_ids") != [aim.permanent_id]:
            return None
        if not game.queue_from_hand(0, card.name, **aimed).supported:
            return None
    settle(game)
    # Delayed abilities: "at the beginning of your next end step" (Necropotence)
    # and "at the beginning of your next upkeep" (Three Wishes).
    game.resolve_end_step(0)
    settle(game)
    game.start_next_turn()
    settle(game)
    game.start_next_turn()
    settle(game)
    return game


def _announced(card) -> bool:
    text = (card.oracle_text or "").lower()
    return any(word in text for word in _ANNOUNCED)


def _named_while_hidden(game) -> list[tuple[str, str, str]]:
    game.log.confirm()
    return list(game.log.named)


def run_census(by_name, rows, *, aim_at_mask=False) -> dict:
    found = {"driven": 0, "undriven": [], "named": {}, "announced": {}}
    for card, shape, index in rows:
        game = drive(by_name, card, shape, index, aim_at_mask=aim_at_mask)
        if game is None:
            found["undriven"].append(f"{card.name} ({shape})")
            continue
        found["driven"] += 1
        named = _named_while_hidden(game)
        if named:
            bucket = "announced" if _announced(card) else "named"
            found[bucket][f"{card.name} ({shape})"] = named
    return found


#: One row in eight in the quick pass, by what the row is (``stable_sample``),
#: so a merge that moves the pool adds rows rather than re-sampling them; the
#: full pass (``MTG_FULL_CENSUS``) drives every row.
_EVERY = 8


def _sampled(rows) -> list[tuple]:
    return [
        row for row in rows
        if stable_sample(f"{row[0].name}:{row[1]}:{row[2]}", _EVERY)
    ]


def test_no_log_line_names_a_hidden_card(pool, by_name):
    """Every card that moves a card through a hidden zone, driven to its next
    upkeep: no line names a card that was hidden as it was written and still
    was at the next line, and was never public in between.

    The floor is what this pool drives — 816 of 895 rows on SCG W2G4's base,
    ~100 in the quick pass's eighth: a census that stops reaching its cards
    reads clean over nothing."""
    census = run_census(by_name, _sampled(hidden_movers(pool)))
    floor = 800 if full_census() else 60
    assert census["driven"] >= floor, (census["driven"], census["undriven"][:20])
    assert census["named"] == {}, census["named"]
    # The excused rows are excused by their own text, and only by it.
    for row in census["announced"]:
        assert _announced(by_name[row.rsplit(" (", 1)[0]]), row


def test_nothing_aimed_at_a_face_down_creature_names_its_card(pool, by_name):
    """Every supported spell and activated ability whose picker offers the
    opponent's face-down creature, aimed at it: the card it hides is named only
    once it is turned up or leaves the battlefield (CR 708.9 reveals it then),
    never while it is face down (CR 708.5).

    The floor is what this pool drives: 863 of 2,446 rows on SCG W2G4's base
    (a row is driven when its picker offers the face-down creature), ~100 in
    the quick pass's eighth."""
    census = run_census(by_name, _sampled(aimers(pool)), aim_at_mask=True)
    floor = 800 if full_census() else 60
    assert census["driven"] >= floor, census["driven"]
    hidden_card_named = {
        row: named for row, named in {**census["named"], **census["announced"]}.items()
        if any(name in _FACE_DOWN for _line, name, _where in named)
    }
    assert hidden_card_named == {}, hidden_card_named

"""Census: an entry trigger never carries a target it could not have chosen.

This engine names an entry trigger's target as its permanent is **cast** — a
convention ``test_entry_trigger_stack_census.py`` measured and kept. CR 603.3d
chooses that target as the trigger is put on the stack, so the cast's
announcement is a *pre-answer* to the trigger's own choice, and it has to be an
answer that choice would have accepted. Nothing asked:

* the cast **picker** was a spell's enumeration, whose per-candidate legality
  (``_validate_cast_targets``) answers "valid" for every permanent spell that
  is not an Aura — so it offered every permanent of the right type. Protection
  from the permanent's colour or from creatures (CR 702.16b), shroud, hexproof
  and the trigger's own printed narrowing ("target **red or green** creature",
  Hunting Drake) were all in the list: 104 entries over 44 permanents on the
  table below;
* nothing stood behind the picker (a permanent spell does not target, so
  CR 601.2c has nothing to refuse), and the **push** rode the announcement onto
  the stack object unread. Nekrataal destroyed a White Knight; sixteen shipped
  permanents acted on a creature protected from them.

Both ends read one list now, ``Game._trigger_target_candidates`` — the list the
same trigger offers when its permanent enters *without* being cast, which was
right all along. This holds three statements about it over the pool:

1. **the picker is that list** (``legality.entry_trigger_cast_targets``),
   compared against the prompt the trigger arms on the "put" road;
2. **whatever a cast names, the stack object carries only what the trigger
   could choose** — the named target where it is legal, and otherwise one the
   trigger chose for itself, or no object at all (CR 603.3d removes a trigger
   with no legal choice). Driven with everything the old picker offered and the
   trigger would not, with a bare seat (what the web route sends when no picker
   ran), and with a legal target that **leaves** or a legal player who **gains
   shroud** while the permanent spell waits to resolve;
3. **a seat that can be asked is asked** — the set-aside announcement becomes
   the ``trigger_target`` prompt, offering the trigger's list.

Validated backwards: with ``cast_announcement_fault`` answering "it stands",
statement 2 fails naming 16 cards by a protected creature and Hunting Drake by
every creature it was handed.

What it does not reach, counted rather than hidden: entry triggers that bind
their object some other way (Goremand). ``_choose_trigger_targets`` makes no
choice for those on any road, so there is no list to hold a cast's
announcement to and it rides the object as before.

It used not to reach the entry triggers whose target is a **card in a
graveyard** (Gravedigger, Karmic Guide) either, for the same reason. They
choose now, so the helpers below read a third kind of slot — a pile and a
position in it — and those cards are held to the first statement here and to
the bare-seat naming of the second. A spell's enumeration of graveyard cards
is the trigger's own, so there is no wider list to name an illegal slot out
of; what is particular to them (a slot the trigger cannot choose, a card that
leaves, the prompt) is driven in ``test_graveyard_trigger_target_census.py``.
"""

from __future__ import annotations

from functools import lru_cache

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import chosen_targets
from engine.targeting import cast_announced_entry_trigger, derive_cast_spec

from .test_entry_trigger_stack_census import _pool

# 60 permanents announce an entry trigger's target as they are cast; the
# trigger makes its own choice on the stack for 44 of them (October 2026).
_MIN_ANNOUNCING = 55
_MIN_JUDGED = 40
# 256 and 168 with a Shroud and a Hexproof guard that have shroud and
# hexproof; 199 and 111 while they were plain creatures.
_MIN_ILLEGAL_NAMINGS = 215
_MIN_SET_ASIDE = 135
_MIN_DEPARTURES = 28
_MIN_MASKED = 8
_MIN_PROMPTS = 20

_BOARD = (
    "Grizzly Bears", "Black Knight", "Ornithopter", "Serra Angel", "Forest",
    "Sol Ring", "Circle of Protection: Red",
)
_YARD = ("Hill Giant", "Lightning Bolt", "Ornithopter", "Holy Strength", "Swamp")
_LIBRARY = ("Forest", "Craw Wurm", "Plains", "Counterspell", "Swamp", "Mountain") * 3


def _guard(label: str, text: str) -> CardDefinition:
    kind = "Creature — Golem"
    return CardDefinition(
        name=f"Census {label}", mana_cost="{3}", cmc=3.0, type_line=kind,
        oracle_text=text, colors=(), color_identity=(),
        # ``keywords`` is what layer 6 reads a printed keyword off; a
        # protection is read off the text. This said ``()`` for every guard,
        # so "Census Shroud" and "Census Hexproof" were two more plain 3/3s
        # and no cast in this file had ever named a shrouded or hexproof
        # creature — see ``test_the_guards_carry_what_their_names_say``.
        keywords=(text,) if text in ("Shroud", "Hexproof") else (), produced_mana=(),
        raw={"name": f"Census {label}", "type_line": kind, "power": "3", "toughness": "3"},
    )


#: Colourless on purpose, so no printed "nonblack" excludes one for a reason
#: other than the immunity it carries.
_GUARDED = tuple(
    _guard(label, text) for label, text in (
        ("Plain", ""),
        ("Shroud", "Shroud"),
        ("Hexproof", "Hexproof"),
        ("Pro White", "Protection from white"),
        ("Pro Blue", "Protection from blue"),
        ("Pro Black", "Protection from black"),
        ("Pro Red", "Protection from red"),
        ("Pro Green", "Protection from green"),
        ("Pro Creatures", "Protection from creatures"),
        ("Pro Artifacts", "Protection from artifacts"),
    )
)


def _table(card, *, interactive=()) -> Game:
    pool = _pool()

    def named(names):
        return [pool[name] for name in names]

    game = Game(players=[
        PlayerState("A", library=named(_LIBRARY), hand=[card], graveyard=named(_YARD)),
        PlayerState("B", library=named(_LIBRARY), graveyard=named(_YARD)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat in (0, 1):
        for entry in named(_BOARD) + list(_GUARDED):
            game._put_permanent_onto_battlefield(seat, Permanent(card=entry), None)
    return game


@lru_cache(maxsize=1)
def _announcing_cards() -> tuple:
    """Every supported permanent whose cast names an entry trigger's target."""
    rows = []
    for card in sorted(_pool().values(), key=lambda entry: entry.name):
        if card.primary_type in ("instant", "sorcery", "land"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if cast_announced_entry_trigger(card, program, optional_cost_payments={}) is None:
            continue
        rows.append(card)
    return tuple(rows)


def _slot(entry: dict) -> tuple:
    if entry.get("kind") == "player":
        return ("player", entry.get("seat"), None)
    if entry.get("kind") == "graveyard":
        # A card in a graveyard, by pile and slot. The cast picker spells the
        # slot ``index`` and the trigger's prompt ``graveyard_index``; one key
        # here so the two lists compare.
        slot = entry["index"] if "index" in entry else entry.get("graveyard_index")
        return ("graveyard", entry.get("seat"), slot)
    return ("permanent", entry.get("seat"), entry.get("index"))


def _own_list(card) -> "set | None":
    """What the trigger offers when *card* enters without being cast: the
    ``trigger_target`` prompt's candidates as picker slots, the empty set when
    it was removed for want of a legal target, None when it chooses nothing."""
    game = _table(card, interactive={0, 1})
    source = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, source, None)
    prompts = [choice for choice in game.pending_choices if choice.kind == "trigger_target"]
    if not prompts:
        removed = any("no legal target" in line for line in game.log[-6:])
        return set() if removed else None
    slots = set()
    for entry in prompts[0].data.get("targets") or ():
        if entry.get("kind") in ("player", "graveyard"):
            slots.add(_slot(entry))
            continue
        permanent = game.permanent_by_id(entry.get("permanent_id"))
        if permanent is not source:
            slots.add((
                "permanent", game.controller_index_of(permanent),
                game.battlefield_index_of(permanent),
            ))
    return slots


def _announce(game, card, slot) -> dict:
    kind, seat, index = slot
    if index is None:
        return {"target_player_index": seat}
    if kind == "graveyard":
        # The pile and the slot of it, which is how a cast names a card there.
        return {"target_player_index": seat, "target_permanent_index": index}
    return {"target_permanent_ids": [game.players[seat].battlefield[index].permanent_id]}


def _cast_and_enter(card, keywords, *, interactive=(), in_response=None) -> "Game | None":
    """Cast *card*, do *in_response*, and resolve the permanent spell — and
    nothing else, so its entry trigger is on the stack unresolved."""
    game = _table(card, interactive=interactive)
    resolved = keywords(game) if callable(keywords) else dict(keywords)
    if not game.queue_from_hand(0, card.name, **resolved).supported:
        return None
    if in_response is not None:
        in_response(game)
    assert game.stack and game.stack[-1].card is card, card.name
    game.resolve_top_of_stack(pause_for_choices=True)
    return game


def _illegal_carried(game, card) -> list[str]:
    """Targets an entry trigger of *card* on the stack carries that it could
    not have chosen for itself, as readable labels."""
    found = []
    for item in game.stack:
        if item.ability_instruction is None or item.source_permanent is None:
            continue
        if item.source_permanent.card is not card:
            continue
        offer = game._trigger_target_candidates(item, announced=True)
        if offer is None:
            continue
        _spec, _chooser, candidates = offer
        legal = {_slot(entry) for entry in candidates}
        for target in chosen_targets(game, item) or ():
            if target.kind == "player":
                slot = ("player", target.seat, None)
                label = f"player {target.seat}"
            elif target.kind == "graveyard":
                where = game.graveyard_index_of(target.stamp)
                if where is None:
                    found.append("a card that has left its graveyard")
                    continue
                slot = ("graveyard", target.stamp.seat, where)
                label = f"{target.stamp.card.name} in a graveyard"
            else:
                permanent = game.permanent_by_id(target.permanent_id)
                if permanent is None or not game.is_on_battlefield(permanent):
                    found.append("a permanent that has left")
                    continue
                slot = (
                    "permanent", game.controller_index_of(permanent),
                    game.battlefield_index_of(permanent),
                )
                label = permanent.card.name
            if slot not in legal:
                found.append(label)
    return found


def _set_aside(game) -> bool:
    return any("chooses again (603.3d)" in line for line in game.log)


def test_the_guards_carry_what_their_names_say():
    """The fixture, asked. Two of these guards were built with ``keywords=()``
    and this engine reads a printed keyword off that field, so the Shroud and
    Hexproof guards had neither: the trigger's own list offered them, nothing
    named them as illegal, and the sweep was 57 namings short of what its
    docstring describes. A sweep whose bait is not bait passes."""
    game = _table(_pool()["Man-o'-War"])
    theirs = {p.card.name: p for p in game.controlled_by(1)}
    assert game._has_keyword(theirs["Census Shroud"], "shroud")
    assert game._has_keyword(theirs["Census Hexproof"], "hexproof")
    assert not game._has_keyword(theirs["Census Plain"], "shroud")
    for label, quality in (
        ("White", ("color", "W")), ("Blue", ("color", "U")), ("Black", ("color", "B")),
        ("Red", ("color", "R")), ("Green", ("color", "G")),
        ("Creatures", ("card_type", "creature")), ("Artifacts", ("card_type", "artifact")),
    ):
        assert quality in game._protection_qualities(theirs[f"Census Pro {label}"]), label

    # …and the list a Man-o'-War's trigger offers leaves out the shrouded one
    # on both seats, the opponent's hexproof one, and — it is a creature's
    # ability — both "protection from creatures" ones.
    offered = {
        (entry["seat"], game.permanent_at(entry["seat"], entry["index"]).card.name)
        for entry in game.cast_target_spec(0, _pool()["Man-o'-War"]).get("valid_targets") or ()
        if entry.get("kind") == "permanent"
    }
    assert {(0, "Census Plain"), (1, "Census Plain"), (0, "Census Hexproof")} <= offered
    assert not {
        (0, "Census Shroud"), (1, "Census Shroud"), (1, "Census Hexproof"),
        (0, "Census Pro Creatures"), (1, "Census Pro Creatures"),
    } & offered


def test_h1_the_cast_picker_is_the_entry_triggers_own_list():
    cards = _announcing_cards()
    assert len(cards) >= _MIN_ANNOUNCING, len(cards)
    judged = 0
    differs: list[str] = []
    for card in cards:
        own = _own_list(card)
        if own is None:
            continue
        judged += 1
        game = _table(card)
        spec = game.cast_target_spec(0, card, optional_cost_payments={})
        picker = {_slot(entry) for entry in spec.get("valid_targets") or ()}
        if picker != own:
            differs.append(
                f"{card.name}: offers {len(picker - own)} the trigger would not, "
                f"withholds {len(own - picker)} it would"
            )
    assert judged >= _MIN_JUDGED, judged
    assert not differs, differs


def test_h1_no_entry_trigger_carries_a_target_it_could_not_choose():
    namings = set_aside = departures = masked = 0
    findings: list[str] = []
    mask = _pool()["Ivory Mask"]

    for card in _announcing_cards():
        own = _own_list(card)
        if own is None:
            continue
        probe = _table(card)
        spec = derive_cast_spec(card, compile_card_oracle(card), optional_cost_payments={})
        # Everything a *spell's* enumeration offers for this spec — the list
        # the cast picker used to be — and both faces.
        wide = {_slot(entry) for entry in probe._enumerate_targets(0, card, dict(spec), for_cast=True)}
        wide |= {("player", 0, None), ("player", 1, None)}
        for slot in sorted(wide - own, key=str):
            game = _cast_and_enter(card, lambda g, slot=slot: _announce(g, card, slot))
            if game is None:
                continue
            namings += 1
            set_aside += _set_aside(game)
            for label in _illegal_carried(game, card):
                findings.append(f"{card.name}: named {slot}, carries {label}")

        legal = sorted(own, key=str)
        target = next(
            (slot for slot in legal if slot[0] == "permanent" and slot[1] == 1),
            next((slot for slot in legal if slot[0] == "permanent"), None),
        )
        if target is not None:
            def leaves(game, target=target):
                permanent = game.players[target[1]].battlefield[target[2]]
                game.remove_from_battlefield(permanent)
                game._permanent_to_graveyard(game.players[target[1]], permanent)

            game = _cast_and_enter(
                card, lambda g, target=target: _announce(g, card, target),
                in_response=leaves,
            )
            if game is not None:
                departures += 1
                for label in _illegal_carried(game, card):
                    findings.append(f"{card.name}: its target left, carries {label}")
        if ("player", 1, None) in own:
            game = _cast_and_enter(
                card, {"target_player_index": 1},
                in_response=lambda g: g._put_permanent_onto_battlefield(
                    1, Permanent(card=mask), None
                ),
            )
            if game is not None:
                masked += 1
                for label in _illegal_carried(game, card):
                    findings.append(f"{card.name}: its target gained shroud, carries {label}")

    assert namings >= _MIN_ILLEGAL_NAMINGS, namings
    assert departures >= _MIN_DEPARTURES, departures
    assert masked >= _MIN_MASKED, masked
    assert not findings, (len(findings), sorted(set(findings))[:24])
    # …and the sweep really did set announcements aside, rather than finding
    # nothing because nothing it named was ever carried.
    assert set_aside >= _MIN_SET_ASIDE, set_aside


def test_h1_a_seat_that_can_be_asked_is_asked_when_its_announcement_is_set_aside():
    """The path this change opens: a cast road that arms ``trigger_target``.
    Offered the trigger's own list, owed by the caster, and the game waits."""
    prompts = 0
    findings: list[str] = []
    for card in _announcing_cards():
        own = _own_list(card)
        if not own:
            continue
        probe = _table(card)
        spec = derive_cast_spec(card, compile_card_oracle(card), optional_cost_payments={})
        wide = {_slot(entry) for entry in probe._enumerate_targets(0, card, dict(spec), for_cast=True)}
        illegal = sorted(wide - own, key=str)
        if not illegal:
            continue
        slot = illegal[0]
        game = _cast_and_enter(
            card, lambda g: _announce(g, card, slot), interactive={0, 1},
        )
        if game is None:
            continue
        owed = [choice for choice in game.pending_choices if choice.kind == "trigger_target"]
        if not owed:
            findings.append(f"{card.name}: named {slot} and nothing was asked")
            continue
        prompts += 1
        choice = owed[0]
        if choice.player_index != 0:
            findings.append(f"{card.name}: the prompt is owed by seat {choice.player_index}")
        offered = set()
        for entry in choice.data.get("targets") or ():
            if entry.get("kind") in ("player", "graveyard"):
                offered.add(_slot(entry))
                continue
            permanent = game.permanent_by_id(entry.get("permanent_id"))
            if permanent.card is card:
                continue  # the permanent that just entered: not on the "put" table
            offered.add((
                "permanent", game.controller_index_of(permanent),
                game.battlefield_index_of(permanent),
            ))
        if offered != own:
            findings.append(f"{card.name}: the prompt offers {sorted(offered ^ own, key=str)[:4]}")
        if game.waiting_prompt() is None:
            findings.append(f"{card.name}: the game does not wait on the prompt")

    assert prompts >= _MIN_PROMPTS, prompts
    assert not findings, findings[:20]

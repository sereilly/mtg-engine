"""CR 613.7 — inside layer 5 the *later* colour effect decides, whatever kind it is.

"Within a layer or sublayer, determining which order effects are applied in is
usually done using a timestamp system. An effect with an earlier timestamp is
applied before an effect with a later timestamp." Every colour effect in this
pool *sets* the colour (CR 105.3: "the new color replaces all previous colors
the object had"), so applied-last is what the permanent is.

``layer_bridge.collect_color_effects`` used to order its channels by a constant
per channel — a permanent's own chosen colour −1, an indefinite recolour 0, a
turn-long one 1, a board-wide static 2, and an Aura's real attach stamp above
all four — so which effect won depended on what *kind* of effect it was. Under
Shifting Sky, Darkest Hour, Celestial Dawn or Thran Lens a later "becomes black
until end of turn" did nothing; Sinister Strength's black survived a Celestial
Dawn that arrived after it; a lace cast after a turn-long recolour lost to it.

This file is the census that defines the fix. It takes every way the pool can
produce a colour effect, grouped by **how CR 613.7 stamps it** —

* a permanent's own static ("This creature is the chosen color", Alloy Golem):
  the object's timestamp, CR 613.7a + 613.7d;
* a board-wide static with a printed colour (Darkest Hour, Celestial Dawn,
  Thran Lens, Dralnu's Crusade) or a chosen one (Shifting Sky), and a
  land-animating static that names a colour (Kormus Bell): the *source's*
  timestamp, CR 613.7a + 613.7d;
* an Aura ("…and is black", Sinister Strength, Grave Servitude; Living
  Terrain's green body): the moment it became attached, CR 613.7e;
* the resolution of a spell or ability, indefinite (the Lace cycle, Prismatic
  Lace, Alchor's Tomb, Quirion Druid's green animation) or until end of turn
  (the five Legends colour spells, Aurora Griffin, Ersatz Gnomes, Raging
  Spirit's own): the moment it was created, CR 613.7b

— and drives **every ordered pair** of them, through the engine's own cast,
activation and entry paths, onto every kind of permanent both reach. After the
second arrives the permanent is the second's colour; when the later one ends
(its source leaves, or cleanup ends a turn-long one) the earlier one shows
again, so an ended effect leaves nothing shadowing what it had overridden
(CR 611.2a, CR 514.2).

Run against the tree before the fix, 145 of the 362 cases failed — 96 of the
222 distinct (first, second) pairs, the six W1G6 measured among them and the
one it measured right not among them. Seven of the 145 failed only at the
*ending*: Kormus Bell's black was written into the indefinite recolour slot,
so the Bell leaving took a lace on the Swamp with it.

Dependency (CR 613.8) outranks timestamps and none exists here, which the last
test holds to the pool rather than assumes: no colour-setting static's scope
asks about colour, and a resolved recolour's set of objects is fixed as it
resolves (CR 611.2c), so no layer-5 effect can change what another applies to.

**Not a characteristic-defining ability.** Alloy Golem's "is the chosen color"
is ordered by its object's timestamp, not ahead of everything under CR 613.3:
the colour it names exists only on the battlefield (CR 614.1c makes the choice
as the permanent enters), and a CDA is information "that would normally be
found elsewhere on that object" and functions in every zone (CR 604.3). So an
Alloy Golem that enters under an older Darkest Hour is the colour it chose.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.models import Permanent

_W2G4_ALL = ("W", "U", "B", "R", "G")

#: The Lace cycle and Legends' five turn-long colour spells, by the colour each
#: prints — one parametrised effect apiece rather than five rows, because what
#: CR 613.7 asks about them does not depend on the word.
_W2G4_LACES = {
    "W": "Purelace", "U": "Thoughtlace", "B": "Deathlace", "R": "Chaoslace",
    "G": "Lifelace",
}
_W2G4_TURN_LONG = {
    "W": "Heaven's Gate", "U": "Sea Kings' Blessing", "B": "Touch of Darkness",
    "R": "Dwarven Song", "G": "Sylvan Paradise",
}

#: What each kind of subject is printed as, and its colour with no effect on it.
_W2G4_SUBJECTS = {
    "bears": ("Grizzly Bears", ["G"]),
    "goblin": ("Goblin Raider", ["R"]),
    "swamp": ("Swamp", []),
    # Two subjects that *are* one of the effects, used only for that effect's
    # rows: an Alloy Golem cast with a colour answered (its "printed" colour
    # is whatever it chose), and the Raging Spirit whose own ability recolours
    # it.
    "golem": ("Alloy Golem", None),
    "spirit": ("Raging Spirit", ["R"]),
}

#: A subject reserved for the one effect it carries.
_W2G4_RESERVED = {"golem": "own_chosen", "spirit": "raging_spirit"}

_W2G4_CREATURES = frozenset({"bears", "goblin", "golem", "spirit"})
_W2G4_EVERYTHING = frozenset(_W2G4_SUBJECTS)

#: Every way the pool produces a layer-5 effect. ``colour`` is the printed one
#: (a list — the empty list is CR 105.2c's colourless) or None where the card
#: asks its controller; ``how`` is the engine path that creates it; ``ends`` is
#: what ends it; ``kinds`` is the colour-writing instruction kind the path runs
#: (none for an effect derived from a static's text). A permanent whose
#: *ability* makes the effect enters before the subject and before either
#: effect, so its own arrival is no part of the order being measured.
_W2G4_EFFECTS = {
    # --- a static's effect: the timestamp of the object it is on (613.7a/d) --
    "own_chosen": dict(
        stamped="object", card="Alloy Golem", colour=None, how="own",
        ends=None, reaches=frozenset({"golem"}),
    ),
    "darkest_hour": dict(
        stamped="source", card="Darkest Hour", colour=["B"], how="permanent",
        ends="leaves", reaches=_W2G4_CREATURES,
    ),
    "celestial_dawn": dict(
        stamped="source", card="Celestial Dawn", colour=["W"], how="permanent",
        ends="leaves", reaches=_W2G4_CREATURES,
    ),
    "thran_lens": dict(
        stamped="source", card="Thran Lens", colour=[], how="permanent",
        ends="leaves", reaches=_W2G4_EVERYTHING,
    ),
    "dralnus_crusade": dict(
        stamped="source", card="Dralnu's Crusade", colour=["B"], how="permanent",
        ends="leaves", reaches=frozenset({"goblin"}),
    ),
    "shifting_sky": dict(
        stamped="source", card="Shifting Sky", colour=None, how="permanent",
        ends="leaves", reaches=_W2G4_CREATURES,
    ),
    "kormus_bell": dict(
        stamped="source", card="Kormus Bell", colour=["B"], how="permanent",
        ends="leaves", reaches=frozenset({"swamp"}), kinds=("animate_all_lands",),
    ),
    # --- an Aura's effect: the moment it became attached (613.7e) -----------
    "sinister_strength": dict(
        stamped="attach", card="Sinister Strength", colour=["B"], how="aura",
        ends="leaves", reaches=_W2G4_CREATURES,
    ),
    "grave_servitude": dict(
        stamped="attach", card="Grave Servitude", colour=["B"], how="aura",
        ends="leaves", reaches=frozenset({"bears", "golem", "spirit"}),
    ),
    "living_terrain": dict(
        stamped="attach", card="Living Terrain", colour=["G"], how="aura",
        ends="leaves", reaches=frozenset({"swamp"}),
    ),
    # --- a resolution's effect: the moment it was created (613.7b) ----------
    "lace": dict(
        stamped="created", card=_W2G4_LACES, colour=None, how="spell",
        ends=None, reaches=_W2G4_EVERYTHING,
        kinds=("recolor_target_from_text",),
    ),
    "prismatic_lace": dict(
        stamped="created", card="Prismatic Lace", colour=None, how="spell",
        ends=None, reaches=_W2G4_EVERYTHING,
        kinds=("recolor_target_chosen_color",),
    ),
    "alchors_tomb": dict(
        stamped="created", card="Alchor's Tomb", colour=None, how="ability",
        ability=0, ends=None, reaches=_W2G4_EVERYTHING,
        kinds=("recolor_target_chosen_color",),
    ),
    "quirion_druid": dict(
        stamped="created", card="Quirion Druid", colour=["G"], how="ability",
        ability=0, ends=None, reaches=frozenset({"swamp"}),
        kinds=("animate_target_indefinitely",),
    ),
    "turn_long_spell": dict(
        stamped="created", card=_W2G4_TURN_LONG, colour=None, how="spell",
        ends="cleanup", reaches=_W2G4_CREATURES,
        kinds=("recolor_targets_until_eot",),
    ),
    "aurora_griffin": dict(
        stamped="created", card="Aurora Griffin", colour=["W"], how="ability",
        ability=0, ends="cleanup", reaches=_W2G4_EVERYTHING,
        kinds=("recolor_targets_until_eot",),
    ),
    "ersatz_gnomes": dict(
        stamped="created", card="Ersatz Gnomes", colour=[], how="ability",
        ability=1, ends="cleanup", reaches=_W2G4_EVERYTHING,
        kinds=("recolor_targets_until_eot",),
    ),
    "raging_spirit": dict(
        stamped="created", card="Raging Spirit", colour=[], how="self",
        ability=0, ends="cleanup", reaches=frozenset({"spirit"}),
        kinds=("recolor_self_until_eot",),
    ),
}

#: Pairs the reach table cannot express: an Aura that enchants a *creature*
#: reaches a Swamp only once another effect has made the Swamp one. It is the
#: only way two colour Auras can sit on one permanent in this pool — both
#: "is black" Auras print the same colour — so it is the Aura-after-Aura row.
_W2G4_EXTRA_PAIRS = (("living_terrain", "sinister_strength", "swamp"),)

#: The colour-writing instruction kinds no row above runs, and the test in
#: this file that drives each one in a game instead.
_W2G4_DRIVEN_ELSEWHERE = {
    "recolor_enchanted_chosen_color":
        "test_w2g4_every_other_recolouring_instruction_is_stamped_when_it_resolves",
    "recolor_self_chosen_color":
        "test_w2g4_every_other_recolouring_instruction_is_stamped_when_it_resolves",
    "animate_self_until_eot":
        "test_w2g4_every_other_recolouring_instruction_is_stamped_when_it_resolves",
}


def _w2g4_card(catalog_by_name, set_pool, name):
    """*name* from the shipped pool, else from Planeshift (still measured)."""
    if name in catalog_by_name:
        return catalog_by_name[name]
    return set_pool("PLS")[name]  # _w2g4_card


def _w2g4_colours(game, perm):
    return sorted(game._effective_colors(perm))  # _w2g4_colours


def _w2g4_table():
    """Two seats, seat 0 to act and asked every question it is owed."""
    game = Game(players=[
        PlayerState(name="A", life=20), PlayerState(name="B", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.active_player_index = 0
    return game  # _w2g4_table


def _w2g4_enter(game, card, seat=0):
    """Put *card* onto *seat*'s battlefield, ready to act."""
    perm = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm  # _w2g4_enter


def _w2g4_settle(game, colour):
    """Resolve the stack, answering each colour question with *colour*.

    Its own loop rather than ``tests.helpers.resolve_stack`` because that one
    answers a blocking prompt with the registry's default, and the colour is
    the whole of what these cases measure.
    """
    for _ in range(40):
        for choice in list(game.pending_choices):
            seat = choice.player_index
            if choice.kind == "enter_choice":
                assert game.confirm_enter_choice(seat, mana_color=colour)
            elif choice.kind == "color_set_choice":
                assert game.confirm_color_set_choice(seat, [colour])
            elif choice.kind == "color_choice":
                assert game.confirm_color_choice(seat, colour)
            else:
                raise AssertionError(f"unexpected prompt {choice.kind!r}")
        if game.stack:
            game.resolve_top_of_stack()
            continue
        if not game.pending_choices:
            return
    raise AssertionError(
        f"did not settle: {[c.kind for c in game.pending_choices]}"
    )  # _w2g4_settle


def _w2g4_cast(game, card, colour=None, *, at=None):
    """Seat 0 casts *card* (at the permanent *at*, if it targets) and the stack
    is settled. Returns the permanent it became, or None for a spell."""
    game.players[0].hand.append(card)
    before = {id(p) for p in game.controlled_by(0)}
    cast = game.queue_from_hand(
        0, card.name,
        **({} if at is None else {"target_permanent_ids": [at.permanent_id]}),
    )
    assert cast.supported, cast.details
    _w2g4_settle(game, colour)
    return next(
        (p for p in game.controlled_by(0)
         if p.card.name == card.name and id(p) not in before),
        None,
    )  # _w2g4_cast


def _w2g4_activate(game, source, index, colour=None, *, at=None):
    """Seat 0 activates *source*'s ability *index* and the stack is settled."""
    source.tapped = False
    activated = game.queue_permanent_ability(
        0, source.card.name, ability_index=index,
        **({} if at is None else {"target_permanent_ids": [at.permanent_id]}),
    )
    assert activated.supported, activated.details
    _w2g4_settle(game, colour)  # _w2g4_activate


class _W2G4Case:
    """One game: a subject, and colour effects arriving on it in order."""

    def __init__(self, catalog_by_name, set_pool):
        self._card = lambda name: _w2g4_card(catalog_by_name, set_pool, name)
        self.game = _w2g4_table()
        self.subject = None
        self.sources = {}
        self.made = {}

    def prepare(self, effect_names):
        """Enter the permanents whose *abilities* will make an effect later."""
        for name in effect_names:
            spec = _W2G4_EFFECTS[name]
            if spec["how"] == "ability" and name not in self.sources:
                self.sources[name] = _w2g4_enter(self.game, self._card(spec["card"]))

    def enter_subject(self, kind):
        self.subject = _w2g4_enter(self.game, self._card(_W2G4_SUBJECTS[kind][0]))
        return self.subject

    def apply(self, name, colour):
        """Create effect *name* through the engine, now. Returns its colour."""
        spec = _W2G4_EFFECTS[name]
        game = self.game
        card_name = spec["card"]
        if isinstance(card_name, dict):
            card_name = card_name[colour]
        wanted = spec["colour"] if spec["colour"] is not None else [colour]
        how = spec["how"]
        if how == "own":
            # The subject itself, cast and answered: its entry is the effect.
            self.subject = self.made[name] = _w2g4_cast(
                game, self._card(card_name), colour,
            )
        elif how == "permanent":
            self.made[name] = _w2g4_cast(game, self._card(card_name), colour)
        elif how == "aura":
            self.made[name] = _w2g4_cast(
                game, self._card(card_name), colour, at=self.subject,
            )
        elif how == "spell":
            _w2g4_cast(game, self._card(card_name), colour, at=self.subject)
        elif how == "self":
            _w2g4_activate(game, self.subject, spec["ability"], colour)
        else:
            _w2g4_activate(
                game, self.sources[name], spec["ability"], colour, at=self.subject,
            )
        assert not game.stack and not game.pending_choices
        return wanted

    def end(self, name):
        """End effect *name* the way its ``ends`` says. False if it cannot."""
        ends = _W2G4_EFFECTS[name]["ends"]
        if ends == "leaves":
            self.game.remove_from_battlefield(self.made.pop(name))
            self.game._recompute_continuous_effects()
            return True
        if ends == "cleanup":
            self.game.resolve_cleanup_step(0)
            return True
        return False


def _w2g4_colour_for(spec, avoid):
    """The colour a choosing effect is answered with: one neither *avoid*
    holds, so two effects in one case never agree by accident."""
    if spec["colour"] is not None:
        return None
    return next(c for c in _W2G4_ALL if [c] not in avoid)  # _w2g4_colour_for


def _w2g4_pairs():
    """Every ordered pair of effects, on every subject both reach.

    A pair is left out only when it cannot be arranged at all, and each reason
    is one of three: the two effects reach no common permanent; both print the
    same colour, so no order can be told from the other by looking; or the
    second is a permanent's own static and the first needs that permanent to
    be on the battlefield already (an Aura or a targeted recolour cannot
    precede the entry of what it is aimed at).
    """
    pairs, left_out = [], []
    for first, a in _W2G4_EFFECTS.items():
        for second, b in _W2G4_EFFECTS.items():
            if first == second and (a["colour"] is not None or a["how"] == "own"):
                continue  # one printed colour twice says nothing
            if second == "own_chosen" and a["stamped"] != "source":
                left_out.append((first, second, "cannot precede its subject"))
                continue
            if a["colour"] is not None and a["colour"] == b["colour"]:
                left_out.append((first, second, "same printed colour"))
                continue
            shared = set(a["reaches"] & b["reaches"])
            for subject, owner in _W2G4_RESERVED.items():
                if owner in (first, second):
                    shared &= {subject}
                else:
                    shared.discard(subject)
            if not shared:
                left_out.append((first, second, "no common subject"))
                continue
            pairs.extend((first, second, subject) for subject in sorted(shared))
    pairs.extend(_W2G4_EXTRA_PAIRS)
    return pairs, left_out  # _w2g4_pairs


_W2G4_PAIRS, _W2G4_LEFT_OUT = _w2g4_pairs()


@pytest.mark.cr("613.7", "613.7a", "613.7b", "613.7d", "613.7e", "105.3")
@pytest.mark.parametrize(
    "first, second, subject_kind", _W2G4_PAIRS,
    ids=[f"{a}>{b}@{s}" for a, b, s in _W2G4_PAIRS],
)
def test_w2g4_the_later_of_two_colour_effects_decides(
    catalog_by_name, set_pool, first, second, subject_kind,
):
    """*first* arrives, then *second*: the permanent is *second*'s colour
    (CR 613.7), whichever two kinds of effect they are — and it is *first*'s
    again when *second* ends, or still *second*'s when *first* is what ends."""
    a, b = _W2G4_EFFECTS[first], _W2G4_EFFECTS[second]
    case = _W2G4Case(catalog_by_name, set_pool)
    case.prepare([first, second])
    printed = _W2G4_SUBJECTS[subject_kind][1]

    first_colour = _w2g4_colour_for(a, avoid=[b["colour"], printed])
    if "own_chosen" not in (first, second):
        case.enter_subject(subject_kind)
    was = case.apply(first, first_colour)
    if second != "own_chosen":
        # (Under an own static arriving second there is no subject yet.)
        assert _w2g4_colours(case.game, case.subject) == was, (
            f"{first} alone should make the {subject_kind} {was}"
        )
    second_colour = _w2g4_colour_for(b, avoid=[was, printed])
    now = case.apply(second, second_colour)
    assert was != now

    assert _w2g4_colours(case.game, case.subject) == now, (
        f"{first} then {second}: CR 613.7 makes the {subject_kind} {now} "
        f"(the later effect), not {was}"
    )

    if first == "own_chosen":
        printed = was
    elif second == "own_chosen":
        printed = now
    if "cleanup" in (a["ends"], b["ends"]):
        # CR 514.2: every turn-long effect ends at once. What is left is the
        # other effect if it outlives the turn, else the permanent as it was.
        case.game.resolve_cleanup_step(0)
        survivor = now if b["ends"] != "cleanup" else (
            was if a["ends"] != "cleanup" else printed
        )
        assert _w2g4_colours(case.game, case.subject) == survivor, (
            f"{first} then {second}, after cleanup"
        )
    elif case.end(second):
        # The later effect is over: the earlier one applies again, with
        # nothing left of the later one to shadow it.
        assert _w2g4_colours(case.game, case.subject) == was, (
            f"{first} then {second}, after {second} ended"
        )
    elif case.end(first):
        assert _w2g4_colours(case.game, case.subject) == now, (
            f"{first} then {second}, after {first} ended"
        )


@pytest.mark.cr("613.7")
def test_w2g4_the_census_examined_every_kind_of_colour_effect_in_both_orders():
    """The floor. A matrix that silently shrank would pass by examining less:
    every way of stamping an effect meets every other in **both** orders, and
    what was left out is exactly the pairs that cannot be told apart or cannot
    be arranged."""
    stamps = {name: spec["stamped"] for name, spec in _W2G4_EFFECTS.items()}
    every_stamp = {"object", "source", "attach", "created"}
    assert set(stamps.values()) == every_stamp
    met = {(stamps[a], stamps[b]) for a, b, _subject in _W2G4_PAIRS}
    # A permanent's own static cannot follow anything aimed at that permanent,
    # nor meet a second own static on the same permanent.
    cannot = {("object", "object"), ("attach", "object"), ("created", "object")}
    assert met == {(x, y) for x in every_stamp for y in every_stamp} - cannot
    # Both durations of a resolved effect meet every stamp, in both orders.
    lasts = {
        name: ("turn" if spec["ends"] == "cleanup" else "indefinite")
        for name, spec in _W2G4_EFFECTS.items() if spec["stamped"] == "created"
    }
    for duration in ("turn", "indefinite"):
        follows = {stamps[a] for a, b, _s in _W2G4_PAIRS if lasts.get(b) == duration}
        precedes = {stamps[b] for a, b, _s in _W2G4_PAIRS if lasts.get(a) == duration}
        assert follows == every_stamp, duration
        assert precedes == every_stamp - {"object"}, duration
    assert len(_W2G4_PAIRS) >= 340, len(_W2G4_PAIRS)
    assert {reason for _a, _b, reason in _W2G4_LEFT_OUT} <= {
        "cannot precede its subject", "same printed colour", "no common subject",
    }


@pytest.mark.cr("613.7d", "613.7a", "400.7")
def test_w2g4_a_static_that_leaves_and_returns_is_stamped_again(
    catalog_by_name, set_pool,
):
    """"An object receives a timestamp at the time it enters a zone." Darkest
    Hour, then Purelace: the Bears are white. Boomerang the Hour and cast it
    again — it is a new object (CR 400.7) with a new timestamp, later than the
    lace, and the Bears are black."""
    card = lambda name: _w2g4_card(catalog_by_name, set_pool, name)  # noqa: E731
    game = _w2g4_table()
    bears = _w2g4_enter(game, card("Grizzly Bears"))
    hour = _w2g4_cast(game, card("Darkest Hour"))
    assert _w2g4_colours(game, bears) == ["B"]
    _w2g4_cast(game, card("Purelace"), at=bears)
    assert _w2g4_colours(game, bears) == ["W"]

    _w2g4_cast(game, card("Boomerang"), at=hour)
    assert hour not in game.controlled_by(0)
    assert _w2g4_colours(game, bears) == ["W"]
    again = _w2g4_cast(game, card("Darkest Hour"))
    assert again is not hour and again.timestamp > hour.timestamp
    assert _w2g4_colours(game, bears) == ["B"]


@pytest.mark.cr("613.7e")
def test_w2g4_an_aura_moved_onto_a_permanent_is_stamped_as_it_attaches(
    catalog_by_name, set_pool,
):
    """"An Aura … receives a new timestamp each time it becomes attached."
    Sinister Strength goes on one creature, *then* a second creature is laced
    white, then Enchantment Alteration moves the Aura onto the second: its
    black is newer than the lace although the Aura is the older permanent."""
    card = lambda name: _w2g4_card(catalog_by_name, set_pool, name)  # noqa: E731
    game = _w2g4_table()
    first = _w2g4_enter(game, card("Grizzly Bears"))
    second = _w2g4_enter(game, card("Hill Giant"))
    aura = _w2g4_cast(game, card("Sinister Strength"), at=first)
    _w2g4_cast(game, card("Purelace"), at=second)
    assert _w2g4_colours(game, first) == ["B"]
    assert _w2g4_colours(game, second) == ["W"]
    attached_at = aura.timestamp

    game.players[0].hand.append(card("Enchantment Alteration"))
    assert game.queue_from_hand(
        0, "Enchantment Alteration", target_permanent_ids=[aura.permanent_id],
    ).supported
    game.resolve_top_of_stack()
    assert game.confirm_permanent_choice(0, second.permanent_id)
    _w2g4_settle(game, None)

    assert aura.metadata["attached_to"] is second
    assert aura.timestamp > attached_at
    assert _w2g4_colours(game, second) == ["B"]
    assert _w2g4_colours(game, first) == ["G"]


@pytest.mark.cr("613.7b", "613.7a")
def test_w2g4_a_block_triggers_recolour_is_newer_than_a_static_already_out(
    catalog_by_name,
):
    """"Whenever this creature blocks or becomes blocked by a creature, that
    creature becomes green." (Aisling Leprechaun.) The one recolour whose
    subject a trigger binds rather than a target names: under a Darkest Hour
    that was already out, the attacker it blocks is green from then on."""
    game = _w2g4_table()
    attacker = _w2g4_enter(game, catalog_by_name["Hill Giant"])
    _w2g4_enter(game, catalog_by_name["Aisling Leprechaun"], seat=1)
    _w2g4_enter(game, catalog_by_name["Darkest Hour"])
    assert _w2g4_colours(game, attacker) == ["B"]

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    declared, why = game.declare_attackers(0, [0])
    assert declared, why
    game.advance_combat_phase()  # declare blockers
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()
    _w2g4_settle(game, None)

    assert _w2g4_colours(game, attacker) == ["G"]


@pytest.mark.cr("613.7b", "613.7a")
def test_w2g4_every_other_recolouring_instruction_is_stamped_when_it_resolves(
    catalog_by_name,
):
    """The three colour-writing instructions no row of the matrix runs, each
    resolving under a Thran Lens that was already out ("All permanents are
    colorless"): the later effect decides, and when it is a turn-long one the
    Lens decides again at cleanup.

    * Dream Coat's "{0}: Enchanted creature becomes the color or colors of
      your choice" — two colours, which is one effect (CR 105.2);
    * Shyft's upkeep "you may have this creature become the color or colors of
      your choice";
    * Treetop Village's "becomes a 3/3 **green** Ape creature … until end of
      turn" — the colour of an animation."""
    card = catalog_by_name.__getitem__
    game = _w2g4_table()
    bears = _w2g4_enter(game, card("Grizzly Bears"))
    village = _w2g4_enter(game, card("Treetop Village"))
    _w2g4_enter(game, card("Thran Lens"))
    for perm in (bears, village):
        assert _w2g4_colours(game, perm) == []

    coat = _w2g4_cast(game, card("Dream Coat"), at=bears)
    assert game.queue_permanent_ability(0, "Dream Coat", ability_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_color_set_choice(0, ["U", "R"])
    _w2g4_settle(game, None)
    assert _w2g4_colours(game, bears) == ["R", "U"]
    # The ability's effect is no part of the Aura (CR 113.7a): it lasts.
    game.remove_from_battlefield(coat)
    game._recompute_continuous_effects()
    assert _w2g4_colours(game, bears) == ["R", "U"]

    _w2g4_activate(game, village, 1)
    assert village.is_creature and _w2g4_colours(game, village) == ["G"]
    game.resolve_cleanup_step(0)
    assert not village.is_creature and _w2g4_colours(game, village) == []

    shyft = _w2g4_enter(game, card("Shyft"))
    assert _w2g4_colours(game, shyft) == []
    game.start_turn(0)
    for _ in range(6):
        if any(c.kind == "color_set_choice" for c in game.pending_choices):
            break
        if game.stack:
            game.resolve_top_of_stack()
        for choice in list(game.pending_choices):
            if choice.kind != "color_set_choice":
                game.auto_resolve_pending_choices(choice.player_index, kinds=[choice.kind])
    assert game.confirm_color_set_choice(0, ["W"])
    _w2g4_settle(game, None)
    assert _w2g4_colours(game, shyft) == ["W"]


def _w2g4_instructions(value, seen=None):
    """Every ``OracleInstruction`` reachable from *value*, nested ones too."""
    from engine.oracle_types import OracleInstruction

    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, OracleInstruction):
        yield value
        yield from _w2g4_instructions(value.payload, seen)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _w2g4_instructions(item, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _w2g4_instructions(item, seen)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield from _w2g4_instructions(getattr(value, field.name), seen)


def _w2g4_whole_pool():
    """Both manifest roles, deduped by name — the cards a colour effect could
    come from, shipped or still measured."""
    from engine.card_loader import load_cards, manifest_set_paths

    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return list(pool.values())  # _w2g4_whole_pool


def _w2g4_colour_writing_kind(instruction):
    """*instruction*'s kind if resolving it writes a colour, else None."""
    from engine.grammar.lowering.categories import INSTRUCTION_CATEGORIES
    from engine.land_animation import LAND_ANIMATION_KIND, land_animation_from_payload

    kind = instruction.kind
    if INSTRUCTION_CATEGORIES.get(kind) == "recolor":
        return kind
    if kind == LAND_ANIMATION_KIND:
        return kind if land_animation_from_payload(instruction.payload).color else None
    if kind.startswith("animate_") and instruction.payload.get("colors"):
        return kind
    return None  # _w2g4_colour_writing_kind


@pytest.mark.cr("613.7b", "613.7a")
def test_w2g4_every_colour_writing_instruction_in_the_pool_is_driven_here():
    """The floor on the other axis: the matrix names its effects by hand, so a
    colour-writing instruction kind the pool compiles and no case here runs
    would be an effect whose stamp nothing has watched. Every such kind, over
    both manifest roles, is run by a row of the matrix or by a named test in
    this file — and each kind the table claims is one the pool still has."""
    from engine.oracle import compiled_units

    pool = _w2g4_whole_pool()
    found = {}
    for card, program in compiled_units(pool):
        for instruction in _w2g4_instructions(program):
            kind = _w2g4_colour_writing_kind(instruction)
            if kind is not None:
                found.setdefault(kind, set()).add(card.name)

    driven = {
        kind for spec in _W2G4_EFFECTS.values() for kind in spec.get("kinds", ())
    } | set(_W2G4_DRIVEN_ELSEWHERE)
    assert set(found) == driven, (
        "colour-writing instruction kinds this census does not drive: "
        f"{sorted(set(found) - driven)}; claimed but not in the pool: "
        f"{sorted(driven - set(found))}"
    )
    for name in _W2G4_DRIVEN_ELSEWHERE.values():
        assert name in globals()
    # "Every kind is driven" over a pool that compiled none is a true
    # statement about nothing.
    assert len(pool) >= 4700, len(pool)
    assert sum(len(cards) for cards in found.values()) >= 38, {
        kind: len(cards) for kind, cards in found.items()
    }


@pytest.mark.cr("613.8a", "611.2c")
def test_w2g4_no_colour_effect_in_the_pool_can_depend_on_another():
    """CR 613.8 overrides timestamps where one effect "would change … what
    [another] applies to". In layer 5 that needs an effect whose reach is
    decided by *colour*, and the pool prints none: every colour-setting static
    describes what it reaches by type, by control or not at all, an Aura's is
    the permanent it is attached to, and a resolved recolour's set of objects
    was fixed as it resolved (CR 611.2c). So timestamp order is the whole of
    the order, which is what the matrix above assumes."""
    from engine import auras, global_statics
    from engine.land_animation import LAND_ANIMATION_KIND, land_animation_from_payload
    from engine.oracle import compiled_units

    pool = _w2g4_whole_pool()
    statics, aura_cards, animators = {}, set(), {}
    for card, program in compiled_units(pool):
        text = card.oracle_text or ""
        static = global_statics.global_static_for(text)
        if static is not None and (
            static.sets_colors is not None or static.sets_chosen_color
        ):
            statics[card.name] = static
        if auras.aura_color_grants(text) or (
            auras.aura_land_animation(text) or {}
        ).get("colors"):
            aura_cards.add(card.name)
        for instruction in program.instructions:
            if instruction.kind == LAND_ANIMATION_KIND:
                animation = land_animation_from_payload(instruction.payload)
                if animation.color:
                    animators[card.name] = animation

    assert set(statics) == {
        "Celestial Dawn", "Darkest Hour", "Dralnu's Crusade", "Shifting Sky",
        "Thran Lens",
    }
    for name, static in statics.items():
        # ``colors`` is the scope's colour narrowing ("**green** creatures
        # have…"); a colour-setting static carrying one would reach a set of
        # permanents another colour effect could move.
        assert static.colors == (), name
    assert aura_cards == {"Grave Servitude", "Living Terrain", "Sinister Strength"}
    assert set(animators) == {"Kormus Bell"}
    assert len(pool) >= 4700, len(pool)

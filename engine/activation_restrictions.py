"""Text-keyed activation restrictions ("Activate only ...", CR 602.5).

The twin of `engine/cast_restrictions.py`, and genuinely textual for the same
reason: the restriction reads the same for any card printed with the phrase, so
it is a table keyed by the printed clause rather than a per-card hook. The
activation path loops it once; a new restricted card is one entry, or none at
all when it prints a clause already here.

What this replaced was two hard-coded phrase checks inside
`mixins/stack/activation.py`, written for two LEA cards. Everything else printed
with the words was **unenforced** -- Caged Zombie's "Activate only if a creature
died this turn" let its controller drain two life on an empty graveyard, and the
card still reported supported, because an unenforced restriction is not a dead
ability. It is an ability that works more often than the card allows, which is
the harder failure to see: nothing crashes, nothing is missing, the game is just
wrong in the player's favour.

Two things follow and are load-bearing:

* **The support gate reads this same table**, so a clause it cannot read makes
  the card unsupported rather than supported-and-unenforced. Every derivation
  table in this engine is arranged that way, and the failure above is why.
* **A clause is matched whole.** Each pattern is anchored, so "Activate only if
  you control a creature with flying" cannot be satisfied by a rule written for
  "Activate only if you control a creature": a restriction matching a prefix
  would be a *weaker* restriction wearing the card's words.
* **A sentence conjoining restrictions is several restrictions**, split by
  `_conjuncts` and all of them required. CR 602.5 puts no limit on how many a
  clause states, and the cards print them as one sentence: "Activate only during
  combat **and only if** defending player controls a snow land" is two rules, and
  Grizzled Wolverine prints three. This was an optional
  ``(?: and only once each turn)?`` tail on three rows -- one row per *pairing*,
  which is quadratic in the clauses that exist and left Speaker of the Heavens as
  a single row reading two rules under one name. A conjunct no row reads makes
  the whole clause unreadable, so a card cannot be admitted with half its
  sentence enforced.

**The table is one table, here, in its order**; what its rows call lives by
family. The moment-of-turn predicates ("…only during your upkeep", "…only
before blockers are declared") are beside it in this module. The predicates
about the state of things — a board, the source, a hand, a graveyard — are
``engine/activation_conditions.py``; the activation caps and the ledgers they
count against are ``engine/activation_tallies.py``; and the sentence reader
every one of them shares (``_clauses``, ``_conjuncts``) is
``engine/activation_clauses.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Callable

from .activation_clauses import _conjuncts, _SELF_SUBJECT, _clauses
from .activation_conditions import (
    _a_creature_died_this_turn,
    _readable_controlled_board,
    _readable_block_partner,
    _blocked_or_was_blocked_by_this_turn,
    _readable_counted_board,
    _controls_the_printed_noun,
    _blocked_by_at_least,
    _seven_life_above_starting,
    _source_in_combat,
    _readable_source_roles,
    _source_not_enchanted,
    _attached_permanent_state,
    _readable_hand_count,
    _exact_cards_in_hand,
    _controlled_since_your_last_turn,
    _source_entered_this_turn,
    _at_least_that_many_counters,
    _no_counters_of_that_kind,
    _readable_cards_above,
    _enough_cards_above_in_graveyard,
    _source_card_is_in_your_graveyard,
    _readable_counted_pile,
    _counted_pile_holds,
)
from .activation_tallies import (
    _PRINTED_FREQUENCY,
    _COUNTED_LIMIT,
    _not_yet_activated_this_turn,
    _below_printed_activation_limit,
    _below_counted_activation_limit,
    _ONCE_ONLY_CLAUSE,
    _not_yet_activated_at_all,
)
# Re-exported for the modules that imported them from here before the
# activation caps moved to ``activation_tallies`` (``mixins/stack/activation.py``,
# ``handlers/control_flow.py``); new code imports them from there.
from .activation_tallies import (  # noqa: F401
    activations_allowed_each_turn,
    activations_this_turn,
    at_activation_limit,
    mark_activated_this_turn,
    mark_once_only_activation,
    printed_activation_caps,
    prints_once_only_restriction,
    reads_activation_tally,
)

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent

#: (game, controller_index, source) -> True when activating is currently legal.
ActivationPredicate = Callable[["Game", int, "Permanent | None"], bool]

#: The same, plus the clause's own match. A clause whose *parameters* are
#: printed -- which step, how many counters of which word -- has to read them,
#: and reading them off the match is what keeps a parameter data instead of
#: baking it into the pattern and needing a row per printing. The same choice
#: `combat_restrictions.py` makes about its land type.
ParameterisedActivationPredicate = Callable[
    ["Game", int, "Permanent | None", "re.Match[str]"], bool
]


@dataclass(frozen=True)
class ActivationRestriction:
    """One printed clause, what it permits, and what to say when it does not."""

    pattern: "re.Pattern[str]"
    is_legal: "ActivationPredicate | ParameterisedActivationPredicate"
    denial: str
    #: Whether `is_legal` takes the match as a fourth argument. Declared rather
    #: than sniffed: a signature guessed by introspection is a signature that
    #: silently stops being guessed right.
    reads_payload: bool = False
    #: Whether `is_legal` takes the whole printed ability **line** as a fourth
    #: argument instead. Declared for the same reason, and separate from
    #: `reads_payload` because the two answer different questions: a payload row
    #: reads the parameters *inside* its own clause, and a line row has to know
    #: which ability the clause is a tail of. CR 602.5c is why one row needs
    #: that -- a use budget spent on one acquired ability says nothing about an
    #: identically worded one -- and the clause alone cannot tell them apart.
    reads_line: bool = False
    #: A denial written from the clause's own printed words, for a row whose
    #: parameters are what the player needs to hear. "You don't have that many
    #: cards in hand" is true of every count and tells nobody which one the card
    #: asks for; "only with exactly seven cards in hand" is the sentence.
    #:
    #: Its own field rather than a format string on :attr:`denial`, because a
    #: row's parameters are not always words that read well in a message — the
    #: board-condition row's capture is a whole noun phrase — and a template
    #: nobody could fill would be a message that renders a regex.
    denial_from_payload: "Callable[[re.Match[str]], str] | None" = None
    #: Whether the clause's *payload* is one this file can act on, asked of the
    #: match alone. A row whose capture ends in `.+` matches more sentences than
    #: it implements -- "controls a snow land" and "controls the highest life
    #: total" are one pattern -- and a clause admitted here with a phrase the
    #: predicate then cannot read would be a restriction that answers "no" for
    #: every board: silent over-restriction, which is this file's own failure
    #: mode pointed the other way. A row that declares one is unmatched where it
    #: says no, so its card is unsupported naming the sentence.
    payload_readable: "Callable[[re.Match[str]], bool] | None" = None
    #: The zone this clause *states* the ability functions in (CR 113.6b:
    #: "an ability that states which zones it functions in functions only from
    #: those zones"). Almost every row leaves it None — "only during your
    #: upkeep" says when, not where — and exactly one says where.
    #:
    #: Declared on the row rather than derived by a second regex somewhere
    #: else, for this file's standing reason: the clause has one reading, and a
    #: module that re-read the sentence to answer "which zone" would be free to
    #: disagree with the module that enforces it. The key it produces is the
    #: same ``functions_from`` ``lowering/_bound_returns.py`` stamps from a
    #: printed "from your graveyard" and ``lower.py`` stamps from an
    #: intervening-if, because the graveyard scan in ``engine/events.py`` and
    #: the activation path in ``mixins/stack/activation.py`` ask one question
    #: of one key.
    functions_from: str | None = None
    #: Whether the clause is a fact about **the board** that can be asked at
    #: any moment — not about timing or priority. "Activate only if you control
    #: a Swamp" (the Tainted lands) is one; "Activate only as an instant"
    #: (Rhystic Cave) is not, because CR 304.5 makes it "the player must have
    #: priority". The tap-for-mana seam runs a mana ability part-way through a
    #: payment, with nobody holding priority (CR 601.2g), and may run one only
    #: when every clause it prints is of this kind — asking it there
    #: (``Game.land_mana_tap_refusal``) rather than leaving it to the
    #: activation path (:func:`restrictions_askable_mid_payment`).
    askable_mid_payment: bool = False


def _as_a_sorcery(game: "Game", controller_index: int, source) -> bool:
    """CR 601.3d's timing: your own main phase, with an empty stack.

    Delegated rather than spelled here, because the cast path asks the identical
    question of Mirage's flash Auras ("any time a sorcery couldn't have been
    cast") — see ``engine/cast_timing.a_sorcery_could_be_cast``. This signature
    stays what the restriction table's rows are: ``(game, seat, source)``.
    """
    from .cast_timing import a_sorcery_could_be_cast

    return a_sorcery_could_be_cast(game, controller_index)


def _as_an_instant(game: "Game", controller_index: int, source) -> bool:
    """CR 602.5e / CR 304.5: the activator must have priority.

    "Activate only as an instant" is not the tautology it looks like, and Lion's
    Eye Diamond is why. CR 605.3a gives an activated *mana* ability three
    windows -- whenever its controller has priority, whenever they are paying
    for a spell or ability, and whenever a rule or effect asks for a mana
    payment -- and the last two are windows in which nobody has priority. This
    clause takes them away, which is the whole of the card: the hand is
    discarded in response to something, never after a spell has been announced
    and its cost is being paid.

    So the question asked is CR 304.5's own -- "the player must have priority"
    -- rather than True. A predicate that returned True would be a restriction
    the engine merely *believes* another rule covers, which is a restriction
    nothing checks the day the payment path grows a mana-ability window.
    """
    return bool(game.has_priority(controller_index))


def _during_any_upkeep(game: "Game", controller_index: int, source) -> bool:
    """"Only during any upkeep step." (Armageddon Clock.) A window scoped to a
    *step* rather than to a player's own step -- the "any player may activate"
    permission is a separate question, and the two together are what let an
    opponent wind the Clock back down."""
    return game.current_step == "upkeep"


def _during_your_upkeep(game: "Game", controller_index: int, source) -> bool:
    """Cyclopean Tomb, the Clockwork creatures, Rock Hydra's pump."""
    return game.current_step == "upkeep" and game.active_player_index == controller_index


def _during_an_opponents_upkeep(game: "Game", controller_index: int, source) -> bool:
    """"Activate only during an opponent's upkeep." (Trade Caravan.)

    The third upkeep window, and a row of its own rather than a tail on
    `_during_your_upkeep` for the reason Norritt is a row beside Nettling Imp:
    the seat *is* the restriction here, and the two clauses are satisfied by
    disjoint turns. The seat test is the spelling
    `_opponents_turn_before_attackers` already uses -- this engine has no teams,
    so every seat that is not yours is an opponent (CR 102.1).
    """
    return game.current_step == "upkeep" and game.active_player_index != controller_index


def _during_their_draw_step(game: "Game", controller_index: int, source) -> bool:
    """"Any player may activate this ability but only during **their** draw
    step." (Well of Knowledge.)

    "Their" is the *activating* seat, not the permanent's controller — the
    whole point of the pairing is that the ability is reachable by everybody and
    each of them may only reach it on their own turn. ``controller_index`` here
    is CR 602.1a's controller of the **ability**, which
    ``_activate_onto_stack`` takes as the activator and names
    ``source_controller_index`` separately for whose battlefield the permanent
    is on; so the seat comparison is already the right one, and this row is the
    draw step's answer to what ``_during_your_upkeep`` answers one step
    earlier.

    A row of its own rather than a spelling of ``_during_any_upkeep``'s
    step-scoped window, for the reason Armageddon Clock's comment beside that
    function gives: "only during any upkeep step" is scoped to the step and
    "only during their draw step" is scoped to a player's own, and reading one
    as the other lets every seat wind this Well four times a turn round a
    four-player table.
    """
    return game.current_step == "draw" and game.active_player_index == controller_index


def _during_your_turn(game: "Game", controller_index: int, source) -> bool:
    """Disrupting Scepter, Instill Energy. The "only once each turn" half of
    Instill Energy's clause is *not* here: it is per-permanent state, not a
    property of the game, and it stays where that state lives."""
    return game.active_player_index == controller_index


def _not_your_turn(game: "Game", controller_index: int, source) -> bool:
    """Ghost Town. The complement of :func:`_during_your_turn`, and printed as a
    negation rather than as "during an opponent's turn" — which is the same set
    of turns in a duel and **not** in a multiplayer game only if a turn could
    belong to nobody, which CR 500.1 does not allow. So one predicate answers
    both spellings, and it is written as the negation the card prints.
    """
    return game.active_player_index != controller_index


def _during_combat(game: "Game", controller_index: int, source) -> bool:
    """Jade Statue."""
    return game.current_turn_phase == "combat"


def _during_declare_blockers(game: "Game", controller_index: int, source) -> bool:
    """Lesser Werewolf. A window scoped to a *step* and to neither player's
    turn: blockers are declared on the defending player's behalf during the
    attacker's turn, so the seat is not part of the question."""
    return game.current_step == "declare_blockers"


def _during_end_of_combat(game: "Game", controller_index: int, source) -> bool:
    """Desert."""
    return game.current_step == "end_of_combat"


def _before_attackers_are_declared(game: "Game", controller_index: int, source) -> bool:
    """Norritt -- the window on its own, with no seat attached.

    Split out of the pair below rather than duplicated, because the two clauses
    are one window and one extra condition: Nettling Imp prints "during an
    opponent's turn, before attackers are declared" and Norritt prints only the
    second half. Two predicates spelling the same window would be two answers to
    when attackers stop being declarable, and the one that was updated later
    would decide which card could be activated.
    """
    if game.current_turn_phase in ("beginning", "precombat_main"):
        return True
    return (
        game.current_turn_phase == "combat"
        and game.current_step in ("beginning_of_combat", "declare_attackers")
        and not game.combat_attackers_locked
    )


def _before_blockers_are_declared(game: "Game", controller_index: int, source) -> bool:
    """"Activate only before blockers are declared." (Acidic Dagger.)

    One combat step later than the window above, and its own predicate for that
    one's stated reason: two spellings of "when is it too late" would be two
    answers, and the one updated later would decide which card could be
    activated. CR 509.1 declares blockers in the declare-blockers step, so every
    step up to and including it is still "before" — the attack has been declared
    by then, which is exactly the window the Dagger wants: its ability names a
    creature that is about to deal combat damage.

    Read off the same lock the attackers window reads, one step over: the
    declaration is what closes the window, not the step's arrival.
    """
    if game.current_turn_phase in ("beginning", "precombat_main"):
        return True
    if game.current_turn_phase != "combat":
        return False
    if game.current_step in ("beginning_of_combat", "declare_attackers"):
        return True
    return (
        game.current_step == "declare_blockers"
        and not game.combat_blockers_locked
    )


def _after_blockers_are_declared(game: "Game", controller_index: int, source) -> bool:
    """"Activate only during combat after blockers are declared." (Trap Runner.)

    The mirror of :func:`_before_blockers_are_declared`, and its own predicate
    for that one's stated reason: two spellings of "has the declaration
    happened" would be two answers, and the one updated later would decide which
    card could be activated. It reads the **same lock**, one step over — CR 509.1
    makes the declaration a turn-based action of the declare-blockers step, so
    the window opens the moment blockers are locked in rather than when the next
    step arrives, which is the priority window of CR 509.2 that Trap Runner is
    printed to be used in.

    Closed at the end of combat, because the clause says "during combat"
    (CR 506.1 names the five steps): the ability makes an attacking creature
    blocked, and outside a combat there is no attacker for it to name.

    A *skipped* declare-blockers step (CR 506.1: skipped when nobody attacked)
    never locks, so the window never opens on a turn with no combat in it —
    which is the honest answer rather than a special case.
    """
    if game.current_turn_phase != "combat":
        return False
    if game.current_step in ("combat_damage", "end_of_combat"):
        return True
    return (
        game.current_step == "declare_blockers"
        and game.combat_blockers_locked
    )


def _opponents_turn_before_attackers(game: "Game", controller_index: int, source) -> bool:
    """Nettling Imp -- the same window `cast_restrictions.py` reads for the same
    printed phrase, narrowed to an opponent's turn."""
    if game.active_player_index == controller_index:
        return False
    return _before_attackers_are_declared(game, controller_index, source)


def _before_combat(game: "Game", controller_index: int, source) -> bool:
    """"Activate only during an opponent's turn and **only before combat**."
    (Maddening Imp.) This is the second conjunct; the first is the
    opponent's-turn row `_not_your_turn` already answers.

    A **wider** window than "before attackers are declared" above, and its own
    predicate for that reason rather than an alias of it: attackers are declared
    in the declare-attackers step (CR 508.1), so the beginning-of-combat step is
    still before *them* — and it is not before *combat*, because CR 506.1's
    phase has begun by then. Reading the two windows as one would let this
    ability be activated one priority later than the card allows, with the
    declaration about to happen, which is the moment the clause exists to
    exclude.

    So the window is the two phases in front of the combat phase (CR 500.1:
    beginning, then precombat main) and nothing after it — the postcombat main
    and ending phases are after combat, not before.
    """
    return game.current_turn_phase in ("beginning", "precombat_main")


def _turn_positions() -> dict[str, int]:
    """Every step of a turn, printed name -> how far through the turn it is.

    Built from the engine's own turn structure rather than listed here, so a
    step this engine grows is orderable the moment it exists and a step it does
    not have cannot be named by a card this table admits. The printed spelling
    is the step key with its underscores opened out -- "combat damage", "end of
    combat" -- which is how the CR prints them.
    """
    from .mixins._constants import _PHASE_STEPS, _TURN_PHASES

    positions: dict[str, int] = {}
    for phase in _TURN_PHASES:
        for step in _PHASE_STEPS.get(phase, (phase,)):
            positions.setdefault(step.replace("_", " "), len(positions))
    return positions


_TURN_POSITIONS = _turn_positions()


def _current_turn_position(game: "Game") -> int | None:
    step = str(getattr(game, "current_step", "") or "").replace("_", " ")
    return _TURN_POSITIONS.get(step)


def _before_step(game: "Game", controller_index: int, source, match) -> bool:
    """"Activate only before the combat damage step." (Angus Mackenzie.)

    A window bounded by a *point in the turn* and by neither player's seat:
    Angus prevents all combat damage this turn, and the damage it is racing is
    dealt on whichever turn it is -- the same reason the seat is not part of
    `_during_declare_blockers`.

    The step is payload. A card printed "only before the end step" needs no code
    here, and a card printed with a step this engine does not have never reaches
    this predicate at all: the pattern is built from the same turn structure, so
    an unreadable step leaves the clause unmatched and its card unsupported.
    """
    here = _current_turn_position(game)
    if here is None:
        return False
    return here < _TURN_POSITIONS[match.group("step")]


#: Matched whole, and no pattern is a prefix of another -- held by
#: `tests/rules/test_activation_restrictions.py`.
ACTIVATION_RESTRICTIONS: tuple[ActivationRestriction, ...] = (
    ActivationRestriction(
        re.compile(r"^activate only if a creature died this turn$"),
        _a_creature_died_this_turn,
        "no creature died this turn",
    ),
    ActivationRestriction(
        # "Activate only if **you control** a creature with flying" (Celestial
        # Enforcer), "…**defending player controls** a snow land" (Arcum's
        # Sleigh), "…**no** snow lands" (Kjeldoran Guard). One row where the
        # first of those was a row with a hand-written predicate: the seat, the
        # noun phrase and the polarity are all payload, so the next card to
        # print the clause about another board or another noun costs nothing.
        # The phrase is read by the grammar's noun parser and validated here —
        # a row ending in `.+` that admitted a phrase its predicate could not
        # read would refuse every activation, silently.
        re.compile(
            r"^activate only if (?P<who>you|defending player) controls? (?P<board>.+)$"
        ),
        _controls_the_printed_noun,
        "that clause's board condition is not met",
        reads_payload=True,
        payload_readable=_readable_controlled_board,
        askable_mid_payment=True,
    ),
    ActivationRestriction(
        re.compile(
            r"^activate only if at least (?P<count>\w+) creatures? "
            r"(?:is|are) blocking this creature$"
        ),
        _blocked_by_at_least,
        "not enough creatures are blocking it",
        reads_payload=True,
    ),
    ActivationRestriction(
        # "Activate only if this creature blocked or was blocked by a blue
        # creature this turn." (Sea Troll.) A *history* clause rather than a
        # board one -- the creature it names may be dead, and the row above asks
        # about a block happening right now. Beside it all the same, because
        # what makes both readable is the one thing: a printed noun phrase the
        # matcher can test, refused by `payload_readable` when it is not.
        re.compile(
            r"^activate only if this creature blocked or was blocked by "
            r"(?P<partner>.+) this turn$"
        ),
        _blocked_or_was_blocked_by_this_turn,
        "it hasn't been in a block with such a creature this turn",
        reads_payload=True,
        payload_readable=_readable_block_partner,
    ),
    ActivationRestriction(
        re.compile(
            r"^activate only if you have at least 7 life more than your "
            r"starting life total$"
        ),
        _seven_life_above_starting,
        "you need 7 life above your starting total",
    ),
    ActivationRestriction(
        # "Activate only if **this creature entered this turn**." (Fungus
        # Elemental.) The printed noun is consumed as a word rather than
        # matched against one spelling: the sentence says whatever the card's
        # own type is, so an artifact or an enchantment printing it needs no
        # second row. Unenforced, this is a +2/+2 counter every turn for the
        # rest of the game on a card that offers one — the ability working
        # more often than the card allows, which is this module's own opening
        # paragraph.
        re.compile(r"^activate only if this (?:permanent|\w+) entered this turn$"),
        _source_entered_this_turn,
        "it didn't enter the battlefield this turn",
    ),
    ActivationRestriction(
        re.compile(r"^activate only as a sorcery$"),
        _as_a_sorcery,
        "this ability is sorcery-speed",
    ),
    ActivationRestriction(
        re.compile(r"^activate only as an instant$"),
        _as_an_instant,
        "this ability may only be activated while you have priority",
    ),
    ActivationRestriction(
        # "Activate only if **enchanted land is untapped**." (Earthlore.) The
        # noun is payload for the reason every other noun in this file is: a
        # card printing the clause about an enchanted creature or an equipped
        # one is this rule, not a new one — and CR 301.5f makes "equipped" the
        # same referent, so both words read the same attachment record.
        #
        # Redundant beside that card's own "Tap enchanted land" cost, and
        # enforced anyway: a restriction the engine merely believes another
        # rule covers is a restriction nothing checks the day the other rule
        # changes.
        re.compile(
            r"^activate only if (?:enchanted|equipped) \w+ is "
            r"(?:(?P<colour>white|blue|black|red|green) and )?"
            r"(?P<state>untapped|tapped)$"
        ),
        _attached_permanent_state,
        "the attached permanent is not in that state",
        reads_payload=True,
    ),
    # --- the eight the shipped pool already printed --------------------------
    # These were a hand-written if-chain in `mixins/stack/activation.py`, each
    # branch a substring test against the ability line. They are here now for
    # the reason this module exists: one declaration per printed clause, read by
    # the activation path *and* by the support gate, so a clause nobody enforces
    # cannot also report as understood.
    ActivationRestriction(
        # Both printed spellings of one clause. Armageddon Clock drops the verb
        # ("Any player may activate this ability but only during any upkeep
        # step"), Tolaria keeps it ("Activate only during any upkeep step") —
        # and the verbless spelling was the only one here, so Tolaria's ability
        # was **unenforced**: usable in any step, with nothing to notice. That
        # is the failure this module was written for, arriving on the second
        # card to print the clause.
        re.compile(r"^(?:activate )?only during any upkeep step$"),
        _during_any_upkeep,
        "only during an upkeep step",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during your upkeep$"),
        _during_your_upkeep,
        "only during your upkeep",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during an opponent's upkeep$"),
        _during_an_opponents_upkeep,
        "only during an opponent's upkeep",
    ),
    ActivationRestriction(
        # Verbless, like Armageddon Clock's: the clause is the tail of an "Any
        # player may activate this ability but only …" sentence, which
        # ``_clauses`` splits and re-heads with "only". The verbed spelling is
        # admitted beside it for that row's reason — the second card to print
        # a clause usually prints the other half of the template, and a row
        # reading one spelling leaves the other unenforced and silent.
        re.compile(r"^(?:activate )?only during their draw step$"),
        _during_their_draw_step,
        "only during their draw step",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during your turn$"),
        _during_your_turn,
        "only during your turn",
    ),
    ActivationRestriction(
        # "Any player may activate this ability but only during **their**
        # turn." (Volrath's Dungeon.) The same window as the row above with the
        # possessive that goes with a *widened* permission: where "your turn"
        # is printed on an ability only its controller may activate, "their
        # turn" is printed beside "any player may activate this ability" and
        # names whoever is activating it.
        #
        # Which is why it shares ``_during_your_turn``'s predicate rather than
        # needing one: that function compares the **activator's** seat against
        # the active player, because ``activation_denial``'s ``controller_index``
        # is the seat doing the activating (``activate_permanent_ability``'s
        # first argument) and not the permanent's controller. The two clauses
        # ask one question; only the printed pronoun differs, and it differs
        # because the permission beside it does.
        #
        # Its own row rather than a widened regex on the one above, for that
        # row's own reason two rows up: the second card to print a clause
        # usually prints the other half of the template, and the halves are
        # printed with different permissions in front of them.
        re.compile(r"^(?:activate )?only during their turn$"),
        _during_your_turn,
        "only during their turn",
    ),
    ActivationRestriction(
        # "Any player may activate this ability but only during their turn
        # **before the end step**." (Mana Cache.) One window with two bounds —
        # whose turn, and how far into it — printed as one phrase with no
        # joining "and only", so `_conjuncts` rightly leaves it whole and no
        # single row above reads it. The two predicates it is made of already
        # exist and are composed rather than copied: the activator's own turn
        # (`_during_your_turn`, which compares the *activating* seat — see the
        # row above) and a point in the turn (`_before_step`, Angus Mackenzie's,
        # whose step is payload built from the engine's own turn structure).
        #
        # Both pronouns, for the row above's stated reason: the predicate is the
        # activator's seat either way, and "your" is what the template prints
        # on an ability nobody else may activate.
        re.compile(
            r"^(?:activate )?only during (?:your|their) turn before the (?P<step>"
            + "|".join(sorted(map(re.escape, _TURN_POSITIONS), key=len, reverse=True))
            + r") step$"
        ),
        lambda game, controller_index, source, match: (
            _during_your_turn(game, controller_index, source)
            and _before_step(game, controller_index, source, match)
        ),
        "only during their turn before that step",
        reads_payload=True,
    ),
    ActivationRestriction(
        # "Activate only if it's not your turn." (Ghost Town.) The row above
        # negated, and it is a row rather than a comment because the clause was
        # **unenforced**: the grammar admits an "Activate only …" sentence only
        # when this table can read it, so a wording with no row here left the
        # whole line refused — which is the loud half. The quiet half is what
        # a row written without a predicate would have been: a land that
        # bounces itself at any time, including in response to its own
        # controller's sorcery, which is exactly what the clause forbids.
        re.compile(r"^activate only if it's not your turn$"),
        _not_your_turn,
        "only if it's not your turn",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during the end of combat step$"),
        _during_end_of_combat,
        "only during the end of combat step",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during the declare blockers step$"),
        _during_declare_blockers,
        "only during the declare blockers step",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during combat$"),
        _during_combat,
        "only during combat",
    ),
    ActivationRestriction(
        # "Activate only if this creature is attacking or blocking." (Sawback
        # Manticore.) Beside the phase row above because the two look alike and
        # are not: that one asks what step the game is in, this asks what the
        # source is *doing*. The printed roles are payload, so the one-role
        # spelling every set prints is this row rather than a second one.
        #
        # ``this [a-z]+`` rather than "this creature", for `_SELF_SUBJECT`'s
        # reason: "Activate only if **Gerrard Capashen** is attacking" reaches
        # here with the card's own name collapsed to that generic noun
        # (CR 201.5), and a row spelled round one noun read the clause as
        # unknown and took the whole ability with it.
        re.compile(
            r"^activate only if this [a-z]+ is "
            r"(?P<roles>attacking(?: or blocking)?|blocking(?: or attacking)?"
            r"|blocked)$"
        ),
        _source_in_combat,
        "this creature is not attacking or blocking",
        reads_payload=True,
        # The denial names the roles the *clause* printed rather than the
        # union this row now reads: a Cinder Crawler told "this creature is not
        # attacking or blocking" is told about a sentence its card does not
        # print. That is exactly what ``denial_from_payload`` is for, and the
        # constant beside it is what a caller with no match still sees.
        denial_from_payload=lambda match: (
            f"this creature is not {match.group('roles')}"
        ),
        payload_readable=_readable_source_roles,
    ),
    ActivationRestriction(
        re.compile(
            r"^activate only during an opponent's turn, before attackers are declared$"
        ),
        _opponents_turn_before_attackers,
        "only during an opponent's turn, before attackers are declared",
    ),
    # "Activate only during an opponent's turn and only before combat."
    # (Maddening Imp.) **Two rows, not one**, because `_conjuncts` splits the
    # printed sentence at "and only" before this table ever sees it — which is
    # the whole point of that splitter: the pairing is not a clause, and a row
    # per pairing is quadratic in the clauses that exist. So the seat half is
    # the row below and the window half is the row after it.
    ActivationRestriction(
        # The positive spelling of Ghost Town's negation, on the same predicate
        # for the reason `_not_your_turn`'s own docstring gives: CR 500.1 gives
        # every turn an active player, so "during an opponent's turn" and "if
        # it's not your turn" are the same set of turns and two predicates would
        # be two answers.
        re.compile(r"^activate only during an opponent's turn$"),
        _not_your_turn,
        "only during an opponent's turn",
    ),
    ActivationRestriction(
        re.compile(r"^activate only before combat$"),
        _before_combat,
        "only before combat",
    ),
    # "Activate only before attackers are declared." (Norritt.) The same window
    # without the seat, and the reason it is a row here rather than an optional
    # tail on the one above: the two are different restrictions, not one clause
    # written two ways -- Norritt may point its own creature at an attack on its
    # controller's turn and Nettling Imp may not.
    ActivationRestriction(
        re.compile(r"^activate only before attackers are declared$"),
        _before_attackers_are_declared,
        "only before attackers are declared",
    ),
    # "Activate only before blockers are declared." (Acidic Dagger.) One combat
    # step later than the pair above, and a row of theirs rather than a tail on
    # either: the Dagger's ability names a creature that is *about to* deal
    # combat damage, so it wants the attack already declared and the blocks not
    # yet — which is a window neither of those two describes.
    ActivationRestriction(
        re.compile(r"^activate only before blockers are declared$"),
        _before_blockers_are_declared,
        "only before blockers are declared",
    ),
    # "Activate only during combat after blockers are declared." (Trap Runner.)
    # The complement of the row above, and beside it rather than folded into
    # the bare "only during combat" one: that window is the whole phase, and
    # this ability may not be used before the blocks are in — an unenforced
    # timing clause is an ability that works more often than the card allows,
    # which is silent and in the player's favour.
    ActivationRestriction(
        re.compile(r"^activate only during combat after blockers are declared$"),
        _after_blockers_are_declared,
        "only during combat after blockers are declared",
    ),
    # "Activate only if you have **no** cards in hand" (Fool's Tome) and
    # "…**exactly seven** cards in hand" (Library of Alexandria). One row: the
    # sentence is the same rule with the number changed, and the number is
    # payload for the reason every parameterised row here gives — the next card
    # to print it about another count costs nothing.
    ActivationRestriction(
        re.compile(
            r"^activate only if you have (?P<count>no|exactly \w+) "
            r"cards? in hand$"
        ),
        _exact_cards_in_hand,
        "you don't have that many cards in hand",
        reads_payload=True,
        payload_readable=_readable_hand_count,
        # The printed number, because "that many" tells the player nothing —
        # and because the row this generalised said "only with exactly seven
        # cards in hand", which is what a message about Library of Alexandria
        # should still say.
        denial_from_payload=lambda match: (
            f"only with {match.group('count')} cards in hand"
        ),
    ),
    ActivationRestriction(
        re.compile(
            r"^activate only if you've controlled this artifact continuously "
            r"since the beginning of your most recent turn$"
        ),
        _controlled_since_your_last_turn,
        "only if you have controlled it since your most recent turn began",
    ),
    # --- the three Legends prints on their own -------------------------------
    # "Activate only once each turn" (Dream Coat) standing *alone*, where the
    # two rows above carry it as an optional tail. The refusal was already
    # enforced -- `mixins/stack/activation.py` substring-matched the words --
    # but the clause was unreadable *here*, which is the gate half: a card whose
    # only restriction is this sentence was admitted by a table that could not
    # say what the sentence means, and the next such card would inherit that.
    # Both halves ask `limits_to_once_each_turn` now.
    ActivationRestriction(
        re.compile(r"^activate only once each turn$"),
        _not_yet_activated_this_turn,
        "only once each turn",
    ),
    # Two parallel branches added this row in the same wave, for Touch of
    # Vitae's granted ability and Goblin Ski Patrol's printed one. This is the
    # line-keyed reading and it serves both; a per-permanent counter cannot
    # follow an ability onto another creature, nor tell two once-only
    # abilities on one permanent apart.
    # "Activate only once." (Touch of Vitae grants it; nothing in the pool
    # prints it on a card of its own.) One word shorter than the row above and a
    # different rule: no turn bounds it, so the budget is spent for as long as
    # the permanent holds the ability. Anchored, so it cannot be satisfied by
    # the per-turn row's sentence, and reading the whole line rather than the
    # clause because CR 602.5c makes the budget the *ability's* rather than the
    # permanent's.
    ActivationRestriction(
        _ONCE_ONLY_CLAUSE,
        _not_yet_activated_at_all,
        "only once",
        reads_line=True,
    ),
    # "Activate no more than twice each turn." (Vampire Bats.) The *only* clause
    # in the pool that does not begin "Activate only", and the one that showed
    # `_clauses` was collecting by that prefix rather than by the verb: the
    # sentence was not a clause here, so the support gate had nothing to refuse
    # and the grammar consumed it verbatim -- a {B} pump with no cap at all,
    # supported, silent, and wrong in its controller's favour every turn. The
    # frequency is payload, so this row is "no more than <n> each turn".
    ActivationRestriction(
        re.compile(r"^activate no more than " + _PRINTED_FREQUENCY + r" each turn$"),
        _below_printed_activation_limit,
        "already activated as many times as it may be this turn",
        reads_payload=True,
    ),
    # "Activate no more times each turn than the number of snow Swamps you
    # control." (Withering Wisps.) The second cap shape in the pool and the
    # first whose number is not printed anywhere on the card -- see
    # `ActivationCap`. The noun phrase is payload and is read by the grammar's
    # noun parser, so the clause is one row rather than one row per noun; a
    # phrase that parser cannot read leaves it unmatched, and the card is
    # unsupported naming the sentence rather than admitted with an uncapped
    # ability.
    ActivationRestriction(
        re.compile(_COUNTED_LIMIT),
        _below_counted_activation_limit,
        "already activated as many times as it may be this turn",
        reads_payload=True,
        payload_readable=_readable_counted_board,
    ),
    # "Activate only if Hakim isn't enchanted." (Hakim, Loreweaver.) The noun is
    # payload because a card printing this of itself may call itself anything --
    # and the card's own *name* is a fourth spelling, collapsed to
    # `_SELF_SUBJECT` before the match so that one row reads them all.
    ActivationRestriction(
        re.compile(r"^activate only if this [a-z]+ isn'?t enchanted$"),
        _source_not_enchanted,
        "it is enchanted",
    ),
    # "Activate only before the combat damage step." (Angus Mackenzie.) The step
    # alternation is built from the engine's own turn structure, so the step is
    # payload and a step the engine does not have leaves the clause unmatched.
    ActivationRestriction(
        re.compile(
            r"^activate only before the (?P<step>"
            + "|".join(sorted(map(re.escape, _TURN_POSITIONS), key=len, reverse=True))
            + r") step$"
        ),
        _before_step,
        "only before that step",
        reads_payload=True,
    ),
    # "Activate only if there are two or more hatchling counters on this
    # artifact." (Triassic Egg.) Number and counter word are both payload.
    ActivationRestriction(
        re.compile(
            r"^activate only if there are (?P<count>[a-z]+) or more "
            r"(?P<counter>[a-z]+) counters on this [a-z]+$"
        ),
        _at_least_that_many_counters,
        "not enough counters on it yet",
        reads_payload=True,
    ),
    # "Activate only if there are no charge counters on this artifact."
    # (Jeweled Amulet, Ice Cauldron.) The floor above with the number at zero,
    # and its own row because "no" is not one of `NUMBER_WORDS` — a clause
    # nobody had listed is not a dead restriction, it is an unenforced one, and
    # these two cards' whole design is that the ability charges once until the
    # counter comes off.
    ActivationRestriction(
        re.compile(
            r"^activate only if there are no (?P<counter>[a-z]+) counters "
            r"on this [a-z]+$"
        ),
        _no_counters_of_that_kind,
        "it already has one of those counters",
        reads_payload=True,
    ),
    # "Activate only if there are seven or more cards in your graveyard."
    # (Odyssey's threshold abilities: the Barbarian Ring cycle, Nomad Decoy,
    # Cabal Inquisitor's "…only as a sorcery **and only if** there are seven
    # or more cards in your graveyard", which `_conjuncts` hands here as its
    # second half.) The whole count is payload — the number, whose pile, and
    # any narrowing on the cards — read by the grammar's own condition reader
    # and validated by `payload_readable`, so a clause that reader cannot turn
    # into a pile count ("in target player's graveyard", "in each graveyard")
    # leaves the sentence unmatched and its card unsupported.
    #
    # Anchored on the closing "graveyard", which is what keeps it off the two
    # counter rows above ("there are two or more hatchling counters on this
    # artifact") and off every other "there are" a later set prints: a pile
    # count somewhere else is a row somebody adds with a card that prints it.
    ActivationRestriction(
        re.compile(
            r"^activate only if (?P<pile>there (?:is|are) .+ graveyards?)$"
        ),
        _counted_pile_holds,
        "that clause's graveyard count is not met",
        reads_payload=True,
        payload_readable=_readable_counted_pile,
        # The printed sentence, because the number is what the player needs:
        # "only if there are seven or more cards in your graveyard".
        denial_from_payload=lambda match: f"only if {match.group('pile')}",
    ),
    # "Activate only if three or more creature cards are above this card."
    # (Ashen Ghoul.) The one clause in the pool that asks about a graveyard's
    # *order*, and the only kind of clause that can: an ability functioning
    # from a graveyard (CR 113.6m) is printed on a card that is itself in the
    # pile. Number and noun are payload, like every other row here.
    ActivationRestriction(
        re.compile(
            r"^activate only if (?P<count>[a-z]+) or more (?P<kind>.+?) cards "
            r"are above this card$"
        ),
        _enough_cards_above_in_graveyard,
        "not enough cards are above it in the graveyard",
        reads_payload=True,
        payload_readable=_readable_cards_above,
    ),
    # "Activate only if this card is in your graveyard." (Carrionette.) The
    # second clause in the pool about a card in the pile rather than a
    # permanent on the battlefield, and the only one that states its zone
    # outright — which is why it is the one row carrying `functions_from`.
    #
    # The noun is "card" and not `this [a-z]+`, deliberately: every other
    # self-referring row here matches the generic noun because which word a
    # card calls itself by says nothing about the rule, and this is the one
    # place it does. "This creature is in your graveyard" is not a sentence
    # Magic prints — a creature is a permanent (CR 110.1) and a permanent is on
    # the battlefield — so the word is the clause's own claim about where the
    # object is, and reading it loosely would let the key be stamped from a
    # sentence that never made the claim.
    ActivationRestriction(
        re.compile(r"^activate only if this card is in your graveyard$"),
        _source_card_is_in_your_graveyard,
        "it is not in your graveyard",
        functions_from="graveyard",
    ),
)


def _matching_entry(clause: str) -> "tuple[ActivationRestriction, re.Match[str]] | None":
    """The one row that reads *clause*, with its match, or None.

    One lookup for the gate and the enforcement, so a clause the gate calls
    readable is the same clause -- and the same row -- the activation path then
    asks. They used to loop the table separately, which is two answers to "which
    rule is this sentence?" waiting to differ.
    """
    for entry in ACTIVATION_RESTRICTIONS:
        match = entry.pattern.match(clause)
        if match is None:
            continue
        if entry.payload_readable is not None and not entry.payload_readable(match):
            continue
        return entry, match
    return None


def activation_restriction_line(sentence: str, card_name: str | None = None) -> bool:
    """Whether one printed sentence is a restriction this module enforces.

    Read by the support gate and by `scripts/parse_coverage.py`, so what is
    enforced and what is claimed cannot drift.

    **Every** conjunct, because a sentence conjoining two restrictions is two
    restrictions: reading one and consuming the line would leave the other
    unenforced, which is the failure this module was written for arriving
    through the joining word instead of through a missing row.
    """
    if card_name:
        from .oracle import _collapse_self_references

        # Lowercased first, for ``_clauses``' reason one function up.
        sentence = _collapse_self_references(
            (sentence or "").lower(), card_name, _SELF_SUBJECT
        )
    cleaned = (sentence or "").strip().lower().rstrip(".")
    conjuncts = _conjuncts(cleaned)
    return bool(conjuncts) and all(
        _matching_entry(clause) is not None for clause in conjuncts
    )


def restriction_functions_from(
    text: str, card_name: str | None = None
) -> str | None:
    """The zone the "Activate only ..." clauses in *text* state the ability
    functions in (CR 113.6b), or None when none of them says.

    Read once, by the compiler, and stamped onto the ability's instruction —
    the same key and the same claim ``lowering/_bound_returns.py`` derives from
    a printed "from your graveyard" and ``lower.py`` derives from an
    intervening-if. Carrionette is why it is needed here as well: its effect
    prints no zone at all ("Exile this card and target creature ..."), so the
    restriction is the only place on the card the zone is stated, and without
    this the ability would compile fine and be activatable from nowhere.

    Every clause is read rather than the first, and a card stating **two**
    different zones returns None: that is not a card anybody has printed, and
    guessing which half to believe is how an ability comes to function from a
    zone its own sentence denies.
    """
    zones = {
        entry.functions_from
        for clause in _clauses(text, card_name)
        for entry, _match in [_matching_entry(clause) or (None, None)]
        if entry is not None and entry.functions_from
    }
    return zones.pop() if len(zones) == 1 else None


#: "X can't be 0." (Aladdin's Lamp, Helm of Obedience.) A constraint on the
#: value chosen for X as the ability is activated (CR 601.2b), which is why it
#: is not one of the ``ACTIVATION_RESTRICTIONS`` rows above: every one of those
#: is answered from the game state alone, and this one is answered from a
#: number the activator has just named — so it cannot be reached through
#: ``activation_denial``'s signature and is enforced beside the {X} payment in
#: ``mixins/stack/activation.py``.
_X_CANT_BE_ZERO = re.compile(r"^x can'?t be 0$")


def x_zero_restriction_line(sentence: str) -> bool:
    """Whether one printed sentence is the "X can't be 0" constraint.

    One reader, asked by three: the grammar production that consumes the
    sentence, the support gate behind it, and the activation gate that enforces
    it. Written down here rather than spelled again at the gate for this
    module's standing reason — a restriction spelled twice is two readings free
    to disagree about the same sentence, and the half that goes wrong is
    silent, because an unenforced restriction is an ability that works *more
    often* than the card allows.
    """
    return bool(_X_CANT_BE_ZERO.match((sentence or "").strip().lower().rstrip(".")))


def unreadable_activation_clauses(
    oracle_text: str, card_name: str | None = None
) -> list[str]:
    """The "Activate only ..." sentences this module does *not* implement.

    The support gate's question: a card with one of these is refused rather than
    admitted with the clause unenforced.
    """
    return [
        clause for clause in _clauses(oracle_text, card_name)
        if not activation_restriction_line(clause)
    ]


@lru_cache(maxsize=None)
def prints_activation_restriction(ability_text: str) -> bool:
    """Whether *ability_text* prints any "Activate only …" clause at all.

    The question a path asks that runs an ability **without** this module's
    gate: the tap-for-mana seam runs a land's {T} mana ability in the middle of
    a payment (CR 601.2g), when nobody has priority and nothing calls
    :func:`activation_denial`. "Activate only as an instant" means the player
    must have priority (CR 304.5) — Rhystic Cave — so an ability printing any
    clause here belongs to the activation path, which enforces it. Collected
    by the same reader the gate uses; *whether* the clause holds right now is
    that gate's question, not this one's.
    """
    return bool(_clauses(ability_text))


def restrictions_askable_mid_payment(
    ability_text: str, card_name: str | None = None,
) -> bool:
    """Whether every "Activate only …" clause *ability_text* prints is a row
    marked :attr:`ActivationRestriction.askable_mid_payment` — a board
    condition the tap seam can ask itself (:func:`activation_denial` answers
    it) — so the ability may be run there rather than only through the
    activation path. False for a line printing none: that question is
    :func:`prints_activation_restriction`'s.

    "{T}: Add {W} or {B}. Activate only if you control a Swamp." (Tainted
    Field.) The tap seam refused every ability printing a clause, so the
    land's coloured ability was unreachable by a tap, by the payment planner
    and by the castable highlight alike, Swamp or no Swamp: the land made
    {C} and nothing else unless its second ability was activated by index.
    """
    clauses = _clauses(ability_text, card_name)
    if not clauses:
        return False
    for clause in clauses:
        found = _matching_entry(clause.rstrip("."))
        if found is None or not found[0].askable_mid_payment:
            return False
    return True


def activation_denial(game, controller_index: int, source, ability_text: str) -> str | None:
    """Why this activation is illegal, or None when it is not.

    *ability_text* is the whole printed ability line, because the clause is its
    tail. Only the clauses on *that* line apply: a permanent with two abilities
    prints its restrictions per ability, and testing the card's whole text would
    gate one ability with the other's rule.
    """
    # The name off the *source*, which every caller already has: a permanent's
    # printed line may name the card (CR 201.5), and a clause left with the name
    # in it matches no row — which for an enforcement path is a restriction
    # silently not applied, this module's own failure mode.
    card = getattr(source, "card", None)
    for clause in _clauses(ability_text, getattr(card, "name", None)):
        found = _matching_entry(clause.rstrip("."))
        if found is None:
            continue
        entry, match = found
        if entry.reads_payload:
            legal = entry.is_legal(game, controller_index, source, match)
        elif entry.reads_line:
            legal = entry.is_legal(game, controller_index, source, ability_text)
        else:
            legal = entry.is_legal(game, controller_index, source)
        if not legal:
            if entry.denial_from_payload is not None:
                return entry.denial_from_payload(match)
            return entry.denial
    return None


#: "**Activated abilities of creatures can't be activated.**" (Cursed Totem.)
#: The board half of CR 602.5, and the exact mirror of
#: ``cast_bans.global_cast_ban``: not a clause the ability prints about
#: itself but a prohibition one permanent imposes on everybody, so it is read
#: off the *board* at every activation rather than off the line being activated.
#:
#: The card type is payload, so "activated abilities of **artifacts** can't be
#: activated" needs no code. **No mana-ability exception**: CR 605 makes a mana
#: ability an activated ability like any other, and this sentence names no
#: exception — which is the whole of what Cursed Totem does to a Bird of
#: Paradise. The Aura clause one file over
#: (``auras``' ``activated_abilities_shut_off``) prints its exception out loud
#: and is a different sentence.
_GLOBAL_ACTIVATION_BAN = re.compile(
    r"^activated abilities of "
    r"(?P<type>artifacts|creatures|enchantments|lands|planeswalkers) "
    r"can't be activated$"
)


def global_activation_ban_line(line: str) -> str | None:
    """The card type *line* forbids anybody from activating abilities of, or None.

    One reader, two callers, exactly as ``global_cast_ban_line`` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    and ``mixins/stack/activation.py`` asks it at CR 602.2 so the line is
    *enforced*. A prohibition that is claimed and not enforced is an artifact
    reporting supported while every ability it names keeps working — the
    failure this file's docstring opens on.

    The type is returned in the singular the type readers use, because that is
    what ``has_type`` answers to; the printed plural is what the sentence
    spells.
    """
    match = _GLOBAL_ACTIVATION_BAN.match(line.strip().lower().rstrip("."))
    return match.group("type").rstrip("s") if match is not None else None


def global_activation_ban(game, permanent) -> str | None:
    """The name of a permanent forbidding *permanent*'s abilities, or None.

    Every battlefield, and no seat comparison: the sentence names nobody, so it
    binds everybody including the banning permanent's own controller.

    ``effective_card`` for the reason the cast ban reads it — a type word a
    CR 613 layer-3 text change rewrote changes which abilities the line stops,
    and this table should not have to know that text can change. The *affected*
    permanent's type is asked through ``has_type`` (layer 4), never the printed
    line, so an animated Swamp is a creature here exactly as it is everywhere
    else.
    """
    for _seat, source in game.permanents_with_controller():
        for raw_line in (source.effective_card.oracle_text or "").splitlines():
            banned = global_activation_ban_line(raw_line)
            if banned is not None and permanent.has_type(banned):
                return source.card.name
    return None


__all__ = [
    "ACTIVATION_RESTRICTIONS",
    "global_activation_ban",
    "global_activation_ban_line",
    "ActivationRestriction",
    "activation_denial",
    "activation_restriction_line",
    "restriction_functions_from",
    "x_zero_restriction_line",
    "unreadable_activation_clauses",
]

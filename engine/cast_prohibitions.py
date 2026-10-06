"""May this card be cast — or this land played — at all? (CR 601.3, CR 305.1.)

"A player can begin to cast a spell only if a rule or effect allows that player
to cast it **and no rule or effect prohibits that player from casting it**."
This module is the second half of that sentence, as **one predicate with three
readers**:

* the cast path (``mixins/stack/casting.py::_cast_onto_stack``), which refuses
  with nothing spent and logs why;
* the AI's proposal gate (``ai_policy._can_cast_with_targets``), which must not
  offer what the cast path will decline — a refused cast breaks no rule and
  costs nothing, so a seat that re-proposes one does nothing for the rest of
  the game, which is what ``simulate_ai_games.py``'s ``refused_casts`` counts;
* the web's castable highlight (``web/state_view._card_castable_now``), which
  must not glow a card whose click is then refused.

**Why it is a table.** Each prohibition below is its own predicate, in the
module that reads its printed sentence, and that has not changed: this is a
*caller*, not a rewrite. What it replaces is three hand-kept lists of which of
those predicates to ask. The cast path asked thirteen, the AI's gate seven and
the highlight two, and nothing made the three agree — so a seat under Steel
Golem, Arcane Laboratory, Cornered Market, City of Solitude, Hand to Hand or
Damping Engine was shown a hand that glowed and clicked a card the engine
refused, and an AI seat proposed the same refused cast every turn. A ban a
later set prints is one row here and is asked by all three by construction.

**The order is the cast path's.** Rows are asked top to bottom and the first
refusal is the one logged, exactly as the run of ``if`` blocks this replaced
logged it — so a board where two prohibitions stand names the same one it
always did.

**A row knows which question it answers.** A land is *played*, never cast
(CR 305.1: "it is never a spell"), and both actions reach the cast path. Most
printed prohibitions say "cast … spells" and bind no land drop; a few say so in
as many words ("…and lands with the chosen names can't be played", Null
Chamber; "can't cast spells **or play lands** with a name…", City in a Bottle).
Each row declares which it binds (:data:`SPELL`, :data:`LAND`) and
:func:`cast_prohibition` asks only the rows that bind the action in front of
it. That declaration is what stopped "Each player can't cast more than one
spell each turn" (Arcane Laboratory) from refusing a land drop after the turn's
one spell, which it did for as long as the cap was asked of every card.

**What is not here**, each because it is a different rule with its own seam:

* *how many* lands a turn has and the prohibitions that are about land drops
  alone ("Players can't play lands", Worms of the Earth; Damping Engine's land
  half; Solfatara) — ``Game._land_play_refusal``, already one answer with three
  readers (``_may_play_another_land``);
* *when* a card may be cast — its own printed clause (``check_cast_timing``),
  sorcery timing and flash (``cast_timing``). A permission, not a prohibition;
* whether a legal *target* exists (``legality.no_legal_cast_target_refusal``,
  CR 601.2c). The one targeting row that **is** here is Peace Talks' standing
  ban (CR 113.3c), because it sits in the cast path's run of refusals and is an
  effect forbidding the cast rather than a board with nothing to aim at.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .auras import controller_cast_ban
from .cast_restrictions import (chosen_name_ban, combat_play_ban,
                                global_cast_ban, global_play_timing,
                                last_cast_color_ban, most_permanents_cast_ban,
                                own_cast_ban, same_name_as_permanent_ban,
                                spell_cap_ban)
from .search_filters import card_has_type
from .spell_prohibitions import casting_forbidden_this_turn

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .models import CardDefinition

#: The action being asked about: beginning to cast a spell (CR 601.3)…
SPELL = "spell"
#: …or playing a land (CR 305.1), which is a special action and never a cast.
LAND = "land"


@dataclass(frozen=True)
class CastProhibition:
    """Why a card may not be cast or played, as the cast path reports it.

    ``kind`` is the row that refused (a key of :data:`CAST_PROHIBITIONS`),
    ``source`` what imposed it — the permanent's name, or the effect for a
    prohibition no permanent prints — and ``details`` the line the cast path
    logs and returns. A reader that only needs yes-or-no compares against None.
    """

    kind: str
    source: str
    details: str


@dataclass(frozen=True)
class ProhibitionRow:
    """One prohibition: its name, which actions it binds, and its predicate.

    ``ask(game, seat, card, from_zone)`` returns ``(source, details)`` when it
    forbids the action and None when it does not. It is handed only a card of a
    kind it binds, so a row that says "cast … spells" never sees a land.
    """

    kind: str
    binds: frozenset[str]
    ask: Callable[["Game", int, "CardDefinition", str], "tuple[str, str] | None"]


def action_of(card: "CardDefinition") -> str:
    """Which question *card* poses: a land is played, everything else is cast.

    ``primary_type``, the test the cast path itself makes one line before this
    run to decide whether a land drop is being spent.
    """
    return LAND if card.primary_type == "land" else SPELL


# --- the rows, in the order the cast path logs them ------------------------


def _set_lockout(game, seat, card, from_zone):
    # "Players can't cast spells or play lands with a name originally printed
    # in the Arabian Nights expansion." (City in a Bottle.) Both verbs are in
    # the sentence, so the row binds both.
    banning = game._set_lockout_banning_card(card)
    if banning is None:
        return None
    return banning, f"can't cast or play {card.name}: banned by {banning}"


def _controller_cast_ban(game, seat, card, from_zone):
    # "Enchanted creature's controller can't cast creature spells." (Brand of
    # Ill Omen.) Imposed on a *player* by an Aura somebody else may control,
    # which is why it is not a timing gate the spell prints about itself.
    aura = controller_cast_ban(game, seat, card)
    if aura is None:
        return None
    return aura, f"can't cast {card.name}: {aura}"


def _own_cast_ban(game, seat, card, from_zone):
    # "**You** can't cast creature spells." (Steel Golem.) The caster's own
    # battlefield alone — an opponent's Golem says nothing about your spells.
    permanent = own_cast_ban(game, seat, card)
    if permanent is None:
        return None
    return permanent, f"can't cast {card.name}: {permanent}"


def _forbidden_this_turn(game, seat, card, from_zone):
    # "Until end of turn, target player can't cast instant or sorcery spells."
    # (Abeyance.) / "Target player can't cast spells this turn." (Orim's
    # Chant.) A resolved effect's record rather than a permanent's text.
    forbidden_type = casting_forbidden_this_turn(game, seat, card)
    if forbidden_type is None:
        return None
    return (
        "an effect this turn",
        f"can't cast {card.name}: {game.players[seat].name} "
        f"can't cast {forbidden_type} spells this turn",
    )


def _global_cast_ban(game, seat, card, from_zone):
    # "Creature spells can't be cast." (Aether Storm.) No seat in the sentence,
    # so every battlefield is asked and its own controller is bound too.
    permanent = global_cast_ban(game, card)
    if permanent is None:
        return None
    return permanent, f"can't cast {card.name}: {permanent}"


def _most_permanents_cast_ban(game, seat, card, from_zone):
    # "A player who controls more permanents than each other player can't play
    # lands or cast artifact, creature, or enchantment spells." (Damping
    # Engine.) The casting half; the land half is `_land_play_refusal`'s, the
    # one gate every land drop goes through.
    leading = most_permanents_cast_ban(game, seat, card)
    if leading is None:
        return None
    return leading, (
        f"can't cast {card.name}: {leading} stops the player who "
        "controls the most permanents"
    )


def _spell_cap(game, seat, card, from_zone):
    # "Each player can't cast more than one spell each turn." (Arcane
    # Laboratory; "**You** can't…", Yawgmoth's Agenda.) Counts *casts*, read
    # off the tally the cast path appends to further down — so a seat that has
    # already cast the cap is at its limit. Spells only: the predicate takes
    # no card, so it is this row's ``binds`` that keeps a land drop out.
    cap = spell_cap_ban(game, seat)
    if cap is None:
        return None
    return cap, f"can't cast {card.name}: {cap} caps this turn's spells"


def _last_cast_color(game, seat, card, from_zone):
    # "Players can't cast spells that share a color with the spell most
    # recently cast this turn." (Mana Maze.)
    maze = last_cast_color_ban(game, seat, card)
    if maze is None:
        return None
    return maze, (
        f"can't cast {card.name}: it shares a color with the spell "
        f"most recently cast this turn ({maze})"
    )


def _own_turn_only(game, seat, card, from_zone):
    # "Players can cast spells and activate abilities only during their own
    # turns." (City of Solitude.) Read off the board, not off the spell:
    # nothing about the card decides it, only whose turn it is. The activation
    # half of the same sentence is `mixins/stack/activation.py`'s.
    permanent = global_play_timing(game, seat)
    if permanent is None:
        return None
    return permanent, f"can't cast {card.name} on another player's turn ({permanent})"


def _combat_play_ban(game, seat, card, from_zone):
    # "During combat, players can't cast instant spells or activate abilities
    # that aren't mana abilities." (Hand to Hand.) ``card_has_type``, not
    # ``primary_type``: CR 205.2a gives a card every type its line names.
    ban = combat_play_ban(game)
    if ban is None or not card_has_type(card, ban[1]):
        return None
    return ban[0], f"can't cast {card.name} during combat ({ban[0]})"


def _targeting_ban(game, seat, card, from_zone):
    # "…players and permanents can't be the targets of spells or activated
    # abilities." (Peace Talks, CR 113.3c.) A spell that must choose a target
    # cannot be announced while nothing may be targeted.
    from .legality import targeting_ban_refusal

    refusal = targeting_ban_refusal(game, card, from_zone=from_zone)
    if refusal is None:
        return None
    source = game.targeting_bans[-1].get("source_name", "an effect")
    return source, refusal


def _chosen_name_ban(game, seat, card, from_zone):
    # "Spells with the chosen names can't be cast and lands with the chosen
    # names can't be played." (Null Chamber.) / "Spells with the chosen name
    # can't be cast." (Meddling Mage.) Both actions reach this row; which the
    # printed line binds is `chosen_name_ban_row`'s answer, read inside.
    permanent = chosen_name_ban(game, card)
    if permanent is None:
        return None
    return permanent, f"can't play {card.name}: {permanent}"


def _same_name_as_permanent(game, seat, card, from_zone):
    # "Players can't cast spells with the same name as a nontoken permanent." /
    # "Players can't play nonbasic lands with the same name as a nontoken
    # permanent." (Cornered Market.) Two printed lines, one per action; the
    # predicate picks the half by what the card is.
    permanent = same_name_as_permanent_ban(game, card)
    if permanent is None:
        return None
    return permanent, f"can't play {card.name}: {permanent}"


_SPELLS = frozenset({SPELL})
_BOTH = frozenset({SPELL, LAND})

#: Every CR 601.3 prohibition the engine enforces, **in the order the cast path
#: asks them**. Adding a ban is adding a row: the cast path, the AI's gate and
#: the castable highlight all read this table and nothing else.
#: ``tests/engine/test_cast_prohibition_readers.py`` holds a scenario per row
#: and fails on a row without one.
CAST_PROHIBITIONS: tuple[ProhibitionRow, ...] = (
    ProhibitionRow("set_lockout", _BOTH, _set_lockout),
    ProhibitionRow("controller_cast_ban", _SPELLS, _controller_cast_ban),
    ProhibitionRow("own_cast_ban", _SPELLS, _own_cast_ban),
    ProhibitionRow("casting_forbidden_this_turn", _SPELLS, _forbidden_this_turn),
    ProhibitionRow("global_cast_ban", _SPELLS, _global_cast_ban),
    ProhibitionRow("most_permanents_cast_ban", _SPELLS, _most_permanents_cast_ban),
    ProhibitionRow("spell_cap_ban", _SPELLS, _spell_cap),
    ProhibitionRow("last_cast_color_ban", _SPELLS, _last_cast_color),
    ProhibitionRow("global_play_timing", _SPELLS, _own_turn_only),
    ProhibitionRow("combat_play_ban", _SPELLS, _combat_play_ban),
    ProhibitionRow("targeting_ban", _SPELLS, _targeting_ban),
    ProhibitionRow("chosen_name_ban", _BOTH, _chosen_name_ban),
    ProhibitionRow("same_name_as_permanent_ban", _BOTH, _same_name_as_permanent),
)


def cast_prohibition(
    game: "Game", seat: int, card: "CardDefinition", *, from_zone: str = "hand"
) -> CastProhibition | None:
    """What forbids *seat* casting (or, for a land, playing) *card*, or None.

    The first row of :data:`CAST_PROHIBITIONS` that binds the action and
    refuses — the same prohibition, with the same words, the cast path logs.
    Pure: it reads the board and the turn's records and changes neither, so the
    AI may ask it of every card in a hand and the highlight on every poll.

    *card* is the spell as it would be cast: for a split card the half
    (CR 709.3a evaluates only the chosen half), which is what the cast path
    hands it and what the highlight's per-face recursion does too.
    """
    action = action_of(card)
    for row in CAST_PROHIBITIONS:
        if action not in row.binds:
            continue
        found = row.ask(game, seat, card, from_zone)
        if found is not None:
            source, details = found
            return CastProhibition(row.kind, source, details)
    return None


__all__ = [
    "CAST_PROHIBITIONS", "CastProhibition", "LAND", "ProhibitionRow", "SPELL",
    "action_of", "cast_prohibition",
]

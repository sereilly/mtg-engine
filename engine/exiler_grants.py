"""What a permanent lets each player do with the cards **they** exiled with it.

"Each player may look at cards they exiled with this enchantment, and they may
play lands and cast spells from among those cards." (Shared Fate.) A static
ability (CR 604.1) of the permanent the cards were exiled with: two
permissions, a look (CR 406.3 lets an effect allow a player to look at a
face-down exiled card) and CR 601.3's play, each scoped to **one seat per
card** — the seat that exiled it — and to the cards exiled *with this
permanent* (CR 607.2a's linked record, ``engine/linked_exile.py``).

Derived from the board on demand, for the reason Yawgmoth's Agenda's
permission is (``cast_permissions.board_graveyard_play``): a stored grant
would have to be taken away when the permanent leaves, and one nobody took
away is a pile that stays open for the rest of the game. "Each Shared Fate
tracks only the cards it exiled. If the Shared Fate which was responsible for
a card being exiled leaves the battlefield, putting another Shared Fate onto
the battlefield will not allow you to play that card again." (Ruling
2008-08-01.) A new permanent is a new object with an empty record (CR 400.7),
so derivation gives that ruling for nothing.

Who exiled each card is the linked entry's ``exiler_index``, written by the
effect that exiled it (``replacements/opponent_library_draws.py``) — which
need not be the permanent's controller: Shared Fate's draws are every
player's, and so are the cards each one exiles.

One reader of the printed line (:func:`exiler_play_line`) for every caller:
the parse claim, the support gate, the coverage channel, and the two
enforcements below.

**A window.** "Each player may play lands and cast spells from among cards
they exiled with this artifact this turn." (Uba Mask.) The same permission
with no look (its cards are exiled face up) and bounded by the turn each card
was exiled on, which its draw replacement stamps on the linked entry
(:data:`EXILED_TURN_KEY`; ``replacements/opponent_library_draws.py``). "You
can't play cards you exiled with Uba Mask on previous turns." (Ruling
2004-12-01.)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .late_modules import LateModules

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .cast_permissions import CastPermission
    from .models import Permanent

_late = LateModules(__package__)


#: The linked entry's key naming the seat that exiled the card
#: (``linked_exile.link_exiled_card``'s ``exiler_index``). One spelling,
#: imported by every reader.
EXILER_KEY = "exiler_index"

#: The linked entry's key naming **the turn** the card was exiled on, a
#: ``turn_state.current_turn_stamp`` (``link_exiled_card``'s ``exiled_turn``).
#: "Each player may play lands and cast spells from among cards they exiled
#: with this artifact **this turn**." (Uba Mask.) "You can't play cards you
#: exiled with Uba Mask on previous turns." (Ruling 2004-12-01.) Absent on
#: every entry whose permission has no window (Shared Fate's).
EXILED_TURN_KEY = "exiled_turn"

#: The two windows a printed exiler permission gives, :func:`exiler_play_scope`'s
#: answers: every card the seat ever exiled with the permanent (Shared Fate),
#: or only those it exiled during the turn being taken (Uba Mask).
ANY_TURN = "any_turn"
THIS_TURN = "this_turn"

_EXILER_NOUN = r"(?:artifact|creature|enchantment|land|permanent)"

_EXILER_PLAY = re.compile(
    rf"^each player may look at cards they exiled with this {_EXILER_NOUN}, "
    r"and they may play lands and cast spells from among those cards$"
)

#: Uba Mask's second line. No look: the cards its first line exiles are face
#: up (CR 406.3 lets every player see them), so there is nothing to grant.
_EXILER_PLAY_THIS_TURN = re.compile(
    r"^each player may play lands and cast spells from among cards they "
    rf"exiled with this {_EXILER_NOUN} this turn$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use
#: for the line, for ``cast_permissions.BOARD_GRAVEYARD_PLAY_CLAIM``'s reason.
EXILER_PLAY_CLAIM = "exiler_play"


def exiler_play_scope(line: str) -> str | None:
    """Which window *line* grants — :data:`ANY_TURN` (Shared Fate's
    look-and-play) or :data:`THIS_TURN` (Uba Mask's play) — or None when it
    is neither, in full.

    Read whole: every half is carried out (the look by
    ``linked_exile.face_down_exiled_cards``, the play by
    ``cast_permissions.permission_for``, the window by
    :func:`exiler_play_permission`), so a printing that dropped a half,
    narrowed what may be played, or named another window is a different
    sentence and stays unclaimed.
    """
    normalized = " ".join((line or "").split()).lower().rstrip(".")
    if _EXILER_PLAY.match(normalized):
        return ANY_TURN
    if _EXILER_PLAY_THIS_TURN.match(normalized):
        return THIS_TURN
    return None


def exiler_play_line(line: str) -> bool:
    """Whether *line* is, in full, one of the exiler permissions above — the
    one reader the parse claim, the support gate and the coverage channel
    ask."""
    return exiler_play_scope(line) is not None


def exiler_play_scopes(permanent: "Permanent") -> frozenset:
    """The windows *permanent*, as layers 1 and 3 leave it (CR 707.2, 612.1),
    grants — so a copy grants over its own record, and one whose text was
    changed or whose abilities were removed grants nothing."""
    return frozenset(
        scope
        for line in (permanent.effective_card.oracle_text or "").splitlines()
        if (scope := exiler_play_scope(line)) is not None
    )


def grants_to_exilers(permanent: "Permanent") -> bool:
    """Whether *permanent* prints Shared Fate's static, the one that grants
    the **look** at a face-down card as well as the play."""
    return ANY_TURN in exiler_play_scopes(permanent)


def _entry_in_window(game, entry: dict, scopes: frozenset) -> bool:
    """Whether *entry*'s card is one *scopes* lets its exiler play now: any
    entry under :data:`ANY_TURN`, and under :data:`THIS_TURN` only one
    stamped with the turn being taken."""
    if ANY_TURN in scopes:
        return True
    if THIS_TURN in scopes:
        return _late.turn_state.stamped_turn_is_now(game, entry.get(EXILED_TURN_KEY))
    return False


def exiler_may_look(permanent: "Permanent", entry: dict, viewer_index: int) -> bool:
    """Whether *viewer_index* may look at the face-down card of *entry*, an
    entry of *permanent*'s record: it exiled the card, and the permanent still
    grants the look. Asked by ``linked_exile.face_down_exiled_cards`` for an
    entry on a permanent on the battlefield; a permanent that left hands its
    entries to the game's register without the look (the static ended with
    it, CR 611.3a)."""
    return entry.get(EXILER_KEY) == viewer_index and grants_to_exilers(permanent)


def exiler_play_permission(
    game, player_index: int, card,
) -> "CastPermission | None":
    """The permission *player_index* has to play *card* — the object, in its
    owner's exile — because they exiled it with a permanent that grants it,
    or None.

    "Play", so a land is covered (CR 305.1 still charges the land drop) and a
    spell is cast at its own timing and for its own cost (ruling 2004-12-01:
    "You need to pay the costs of any cards you play from the Exile zone").
    The pile is the card's **owner's** exile — the engine keeps each exiled
    card in its owner's ``PlayerState.exile`` — an opponent's, for a card
    exiled off that opponent's library, named by ``zone_player_index``, the
    cross-seat spelling Grinning Totem's grant made.

    Uba Mask's window is the entry's own: a card it exiled on an earlier turn
    is still linked to it (and still exiled — "Any cards you don't play just
    remain exiled when the turn ends", ruling 2004-12-01) but no longer
    covered (:func:`_entry_in_window`).
    """
    CastPermission = _late.cast_permissions.CastPermission
    linked_entries = _late.linked_exile.linked_entries

    for permanent in game.all_permanents():
        entries = [
            entry for entry in linked_entries(permanent)
            if entry.get(EXILER_KEY) == player_index and entry.get("card") is card
        ]
        if not entries:
            continue
        scopes = exiler_play_scopes(permanent)
        if not scopes:
            continue
        for entry in entries:
            if not _entry_in_window(game, entry, scopes):
                continue
            owner = int(entry.get("owner_index", -1))
            if not 0 <= owner < len(game.players):
                continue
            if not any(held is card for held in game.players[owner].exile):
                continue
            return CastPermission(
                player_index=player_index, zone="exile", mode="play",
                cards=[card], duration=None, source_name=permanent.card.name,
                source_permanent_id=permanent.permanent_id,
                zone_player_index=owner,
            )
    return None

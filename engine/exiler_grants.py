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
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .cast_permissions import CastPermission
    from .models import Permanent


#: The linked entry's key naming the seat that exiled the card
#: (``linked_exile.link_exiled_card``'s ``exiler_index``). One spelling,
#: imported by every reader.
EXILER_KEY = "exiler_index"

_EXILER_PLAY = re.compile(
    r"^each player may look at cards they exiled with this "
    r"(?:artifact|creature|enchantment|land|permanent), and they may play "
    r"lands and cast spells from among those cards$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use
#: for the line, for ``cast_permissions.BOARD_GRAVEYARD_PLAY_CLAIM``'s reason.
EXILER_PLAY_CLAIM = "exiler_play"


def exiler_play_line(line: str) -> bool:
    """Whether *line* is, in full, the look-and-play static above.

    Read whole: both permissions are carried out (the look by
    ``linked_exile.face_down_exiled_cards``, the play by
    ``cast_permissions.permission_for``), so a printing that dropped either
    half, or narrowed what may be played, is a different sentence and stays
    unclaimed.
    """
    return _EXILER_PLAY.match(" ".join((line or "").split()).lower().rstrip(".")) is not None


def grants_to_exilers(permanent: "Permanent") -> bool:
    """Whether *permanent*, as layers 1 and 3 leave it (CR 707.2, 612.1),
    prints the static — so a copy of a Shared Fate grants over its own
    record, and one whose text was changed or whose abilities were removed
    grants nothing."""
    return any(
        exiler_play_line(line)
        for line in (permanent.effective_card.oracle_text or "").splitlines()
    )


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
    """
    from .cast_permissions import CastPermission
    from .linked_exile import linked_entries

    for permanent in game.all_permanents():
        entries = [
            entry for entry in linked_entries(permanent)
            if entry.get(EXILER_KEY) == player_index and entry.get("card") is card
        ]
        if not entries or not grants_to_exilers(permanent):
            continue
        for entry in entries:
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

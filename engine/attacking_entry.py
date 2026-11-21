"""A permanent put onto the battlefield attacking (CR 508.4, 506.3).

CR 508.4: "If a creature is put onto the battlefield attacking, its controller
chooses which defending player, planeswalker a defending player controls, or
battle a defending player protects it's attacking as it enters the battlefield
(unless the effect that put it onto the battlefield specifies what it's
attacking). … Such creatures are 'attacking' but, for the purposes of trigger
events and effects, they never 'attacked.'"

Two roads reach it: a token made "tapped and attacking" (M21's Basri Ket,
``handlers/tokens._token_arrived``) and a card put from a hand with ninjutsu
(CR 702.49a, ``handlers/hand.put_source_card_from_hand_onto_battlefield``).
They wrote the combat record by hand in one place and would have in two, so
:func:`enter_attacking` is the one write: the attacker's slot in
``combat_attackers``, the planeswalker it attacks if any, CR 508.8's record
that the combat has an attacker, and the permanent's own status. Nothing here
announces an attack — the creature was never declared (CR 508.4), so no
"whenever … attacks" trigger fires and no declaration restriction applies
(CR 508.4c).

**Unblocked** needs no write. CR 508.4d / 506.3d: a creature put onto the
battlefield attacking during the declare blockers, combat damage or end of
combat step enters unblocked, and ``Permanent.blocked`` is False on a new
object; before blockers are declared it is neither, which is
``Game.blockers_have_been_declared``' half of the reading
(``subject_filters.subject_matches``' ``unblocked_only``).

:func:`attack_target_of` is the read the other way: what an attacking creature
is attacking, taken **before** it leaves — CR 702.49c enters the Ninja
"attacking the same player, planeswalker, or battle as the creature that was
returned", and once returned that creature is removed from combat (CR 506.4)
and its slot is gone. ``Game.activate_from_hand`` writes the answer onto the
stack object under :data:`ENTERS_ATTACKING`, and the resolving handler reads it
back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent

#: ``StackItem.choices`` key: what a permanent this object puts onto the
#: battlefield attacking is to attack — ``{"seat": int, "planeswalker_id":
#: int | None}``, from :func:`attack_target_of`. Written by the cost that
#: fixed it (ninjutsu's return, CR 702.49c).
ENTERS_ATTACKING = "enters_attacking"


def attack_target_of(game: "Game", permanent: "Permanent") -> dict | None:
    """What *permanent* is attacking right now — ``{"seat", "planeswalker_id"}``
    — or None when it is not an attacking creature with a defender.

    Read off the combat record by the permanent's slot on the attacking seat's
    battlefield (``combat_attackers`` is keyed so), so it must be asked while
    the permanent is still there.
    """
    if not getattr(permanent, "attacking", False):
        return None
    slot = game.battlefield_index_of(permanent)
    if slot is None or game.controller_index_of(permanent) != game.active_player_index:
        return None
    seat = game.combat_attackers.get(slot)
    if not isinstance(seat, int):
        return None
    return {
        "seat": seat,
        "planeswalker_id": game.combat_attacked_planeswalkers.get(slot),
    }


def enter_attacking(
    game: "Game", permanent: "Permanent", *, seat: int,
    planeswalker_id: int | None = None,
) -> bool:
    """Make *permanent*, just put onto the battlefield, an attacking creature
    attacking *seat* (and *planeswalker_id*, a planeswalker that seat
    controls) — CR 508.4. Returns whether it is attacking afterwards.

    It is not, and nothing is written, where the rules say the permanent
    enters but is never an attacking one:

    * there is no combat to join (CR 508.4 speaks of a combat phase);
    * the permanent is no creature (CR 506.3a);
    * it is under the control of a player other than the attacking player
      (CR 506.3b) — the active player, the only attacking player here;
    * the player it would attack is no longer in the game, or is the attacking
      player, or the planeswalker it would attack is no longer on the
      battlefield as a planeswalker that player controls (CR 508.4a, 506.3c),
      in which case it attacks nothing at all rather than the player.
    """
    if game.current_turn_phase != "combat":
        return False
    if not permanent.is_creature:
        return False
    if game.controller_index_of(permanent) != game.active_player_index:
        return False
    if not (0 <= seat < len(game.players)) or seat == game.active_player_index:
        return False
    if game.players[seat].lost:
        return False
    if planeswalker_id is not None:
        walker = game.permanent_by_id(planeswalker_id)
        if (
            walker is None
            or not walker.has_type("planeswalker")
            or game.controller_index_of(walker) != seat
        ):
            return False
    slot = game.battlefield_index_of(permanent)
    if slot is None:
        return False
    game.combat_attackers[slot] = seat
    if planeswalker_id is not None:
        game.combat_attacked_planeswalkers[slot] = planeswalker_id
    # CR 508.8: "put onto the battlefield attacking" keeps the declare
    # blockers and combat damage steps as a declared attacker does.
    game.combat_creatures_attacked = True
    permanent.attacking = True
    permanent.defending_player_index = seat
    return True


__all__ = ["ENTERS_ATTACKING", "attack_target_of", "enter_attacking"]

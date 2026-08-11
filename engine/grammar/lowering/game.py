"""Lowering tokens, life, and whole-game effects.

Token creation (paired with the generic `create_token` instruction kind, so a
token-making card is a production plus a lowering and never a bespoke handler),
life gain and loss, extra turns, and winning or losing the game.

Grouped as "the game and its players" rather than "the board": none of these
changes what a permanent is, and all of them change the state a player is in.
"""

from ...oracle_types import OracleInstruction
from ...tokens import default_token_name
from .. import ast
from ..errors import LoweringError
from ._common import (
    _amount_payload,
    _describe_targets,
)


# ---------------------------------------------------------------------------
# Life
# ---------------------------------------------------------------------------


def _lower_gain_life(
    node: ast.GainLife, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    recipient = "caster" if node.player.kind == "you" else "target"
    if isinstance(node.amount, ast.ThatMuch):
        # "You gain life equal to the damage dealt" — reads the value the
        # preceding damage instruction recorded in the resolution scratchpad,
        # which is what lets the two effects be separate instructions at all.
        #
        # That only holds when the producer is in *this* resolution. On a
        # triggered ability ("Whenever this creature deals damage, you gain that
        # much life") the amount comes from the trigger's captured event, which
        # is a different mechanism — so refuse rather than read an empty
        # scratchpad and silently gain 0 life.
        if node.amount.source not in produced:
            raise LoweringError(
                f"back-reference to {node.amount.source!r} with no producer in this effect",
                node=node,
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {"amount_from": node.amount.source, "recipient": recipient},
            ),
        )
    payload: dict[str, object] = {
        "amount": _amount_payload(node.amount), "recipient": recipient,
    }
    _describe_targets(payload, node.player)
    return (OracleInstruction("target_gains_life", "", payload),)


def _title(words: str) -> str:
    """Title-case a lexed vocabulary word, preserving multiword entries."""
    return " ".join(part.capitalize() for part in words.split())


def _lower_create_token(node: ast.CreateToken) -> tuple[OracleInstruction, ...]:
    """"Create a 1/1 colorless Insect artifact creature token with flying named
    Wasp." (The Hive.)

    ``create_token`` builds the token's ``CardDefinition`` from the payload
    (engine/tokens.py), so this is pure characteristic transcription: the type
    line is re-rendered in the order the card printed it, and each optional key
    is emitted only when the card states it — matching the legacy rule, whose
    Hive payload carries no ``colors`` entry for a colourless token and no
    ``count`` for a single one.

    An unnamed token takes its CR 111.4 name — its subtype(s) plus the word
    "Token" ("Dwarf Berserker Token") — through ``default_token_name``, the
    one naming rule every token maker shares. Two shapes still refuse rather
    than guess:

    * **A token with neither a printed name nor a subtype.** CR 111.4 has
      nothing to build a name from.
    * **A token with no creature type at all.** ``make_token_card`` always
      builds a creature card, and a type line with no card types would come out
      as a bare subtype the loader could not classify.
    """
    if "creature" not in node.types:
        raise LoweringError("make_token_card only builds creature tokens", node=node)
    if node.name:
        name = _title(node.name)
    elif node.subtypes:
        name = default_token_name(node.subtypes)
    else:
        raise LoweringError(
            "a token with neither a printed name nor a subtype has no CR 111.4 "
            "name to take",
            node=node,
        )

    type_line = " ".join(_title(word) for word in node.types)
    if node.subtypes:
        type_line += " — " + " ".join(_title(word) for word in node.subtypes)

    payload: dict[str, object] = {
        "name": name,
        "power": node.power,
        "toughness": node.toughness,
        "type_line": type_line,
    }
    if node.colors:
        payload["colors"] = node.colors
    if node.keywords:
        payload["keywords"] = tuple(_title(word) for word in node.keywords)
    count = _amount_payload(node.count)
    if count != 1:
        payload["count"] = count
    return (OracleInstruction("create_token", "", payload),)


def _lower_extra_turn(node: ast.ExtraTurn) -> tuple[OracleInstruction, ...]:
    """"Take an extra turn after this one." (Time Walk, Time Vault.)

    ``grant_extra_turn`` queues the turn for the effect's *controller*; it takes
    no player argument. A card handing the extra turn to someone else is a
    different effect, so it is refused rather than lowered onto a handler that
    would give the turn to the wrong player.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no handler for {node.player.kind!r} taking an extra turn", node=node
        )
    return (OracleInstruction("grant_extra_turn", "", {}),)


# Who a "loses the game" sentence names, and the handler that makes that player
# lose. `player_loses_game` and `target_player_loses_game` are the *same*
# function (engine/handlers/life_and_game.py registers both names) and it picks
# the loser off the kind, so the two are not interchangeable: emitting the
# targeted kind for "you lose the game" would kill whoever the spell happened to
# point at.
_LOSE_GAME_KINDS = {
    "you": "player_loses_game",
    "target_player": "target_player_loses_game",
    "target_opponent": "target_player_loses_game",
}


def _lower_lose_game(node: ast.LoseGame) -> tuple[OracleInstruction, ...]:
    """"Target player loses the game." / "You lose the game." (CR 104.3e.)"""
    kind = _LOSE_GAME_KINDS.get(node.player.kind)
    if kind is None:
        raise LoweringError(
            f"no handler makes {node.player.kind!r} lose the game", node=node
        )
    return (OracleInstruction(kind, "", {}),)


def _lower_win_game(node: ast.WinGame) -> tuple[OracleInstruction, ...]:
    """"You win the game." (CR 104.2b.)

    ``player_wins_game`` wins for the effect's *controller* — it marks every
    other player as having lost (104.2a) and takes no player argument. A card
    handing the win to someone else is refused rather than lowered onto a
    handler that would win it for the wrong seat.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no handler makes {node.player.kind!r} win the game", node=node
        )
    return (OracleInstruction("player_wins_game", "", {}),)


def _lower_lose_life(node: ast.LoseLife) -> tuple[OracleInstruction, ...]:
    payload: dict[str, object] = {"amount": _amount_payload(node.amount)}
    if node.player.kind in ("target_player", "target_opponent", "that_player"):
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind == "you":
        # "You lose 3 life" (Grim Tutor) — the same recipient key deal_damage
        # and target_gains_life read.
        payload["recipient"] = "caster"
        return (OracleInstruction("target_loses_life", "", payload),)
    if node.player.kind == "each_opponent":
        payload["recipient"] = "each_opponent"
        return (OracleInstruction("target_loses_life", "", payload),)
    raise LoweringError(f"unsupported life-loss target {node.player.kind!r}", node=node)

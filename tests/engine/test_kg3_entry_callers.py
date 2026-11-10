"""Every caller of the entry seam does what it does to the permanent **after**
the entry â€” through ``then`` (CR 614.12a).

An "as it enters" choice is made before the permanent enters, so at a table
that holds for answers (a person, the simulator's driver) an entry that asks a
question waits on its way until the answer (``engine/entry_awaiting.py``): when
``Game._put_permanent_onto_battlefield`` returns, the permanent may be on no
battlefield yet. Whatever a caller does to it there â€” attach it, tap it and
make it attack, untap it under a rider, put the counters it returns with on it,
grant it haste â€” has to be handed in as ``then``, which the seam runs once the
permanent is there: at once, or at the last answer. Written after the call, it
is done to a permanent that has not arrived (an Aura attached to it from no
zone, a token made attacking with no battlefield slot, a land untapped before
it is a land anyone controls).

This is the census of part 4 of the Known-gaps entry: every call site in
``engine/`` (and the three helpers that return the permanent they entered),
read off the source. A call that names its permanent in a variable and refers
to that variable in a statement the call can reach afterwards must pass
``then``, or be in ``_REVIEWED`` with the reason that reference is right for a
permanent on its way. Backwards: with the conversions undone (the 18 call sites
the census found on the base), it names them.
"""
from __future__ import annotations

import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "engine"

#: The entry seam itself, and the three helpers that hand the entered
#: permanent back to their caller (their callers are held to the same rule).
_SEAM = "_put_permanent_onto_battlefield"
_RETURNING = ("leave_linked_exile", "_reanimate_creature_to_battlefield", "create_token_copy")

#: ``(module, function) -> why its later reference is right for a permanent
#: still on its way``. Each was read; a new entry needs the same.
_REVIEWED = {
    ("mixins/oracle_instructions.py", "_apply_aura_effect"): (
        "Animate Dead attaches itself to the creature it reanimates at once: "
        "the Aura is on the battlefield and ``_resolve_card`` bins an Aura "
        "left unattached (CR 303.4g) the moment this returns. Its resolution "
        "is held while the creature's choice is owed, so no state-based check "
        "sees the host before it arrives; the tapped flag set on the object "
        "is the state it enters with."
    ),
    ("mixins/permanent_state.py", "create_token_copy"): (
        "returns the token; the board-wide lord recompute after the call is "
        "repeated by the entry's own completion."
    ),
    ("handlers/tokens.py", "create_copy_token"): (
        "metadata and id records on the token (who made it, the result "
        "``that token`` names) â€” written to the object, which keeps them "
        "on its way; the log line is the effect's."
    ),
    ("handlers/tokens.py", "_copy_exiled_cards"): (
        "Soul Foundry's token copy of the exiled card: the same two records "
        "``create_copy_token`` writes (who made it, the result ``that token`` "
        "names), written to the object, which keeps them on its way; the log "
        "line is the effect's."
    ),
    ("handlers/linked_exile.py", "put_exiled_cards_into_zone"): (
        "the newcomers kept for the one summary line written once the "
        "event has closed, which names only those no replacement took away "
        "(``entry_awaiting.entry_replaced``) — nothing is done to them."
    ),
    ("piles.py", "_graveyard_fates"): (
        "``arrived is not None`` â€” whether a card came back, for the log."
    ),
}


def _names(node) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _parents(tree) -> dict:
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def _reachable_after(stmt, parent, func) -> list:
    """The statements *stmt*'s completion can reach in *func*: the rest of its
    block, then the rest of each enclosing block, stopping at a statement
    that leaves (return / raise / continue / break)."""
    out = []
    node = stmt
    while node is not func:
        holder = parent[node]
        for field in ("body", "orelse", "finalbody", "handlers"):
            block = getattr(holder, field, None)
            if isinstance(block, list) and node in block:
                rest = block[block.index(node) + 1:]
                for later in rest:
                    out.append(later)
                    if isinstance(later, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                        return out
                break
        node = holder
    return out


def _calls_of(tree, names):
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in names
            ):
                yield func, node


def _innermost_function(node, parent):
    while node in parent:
        node = parent[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _entered_variable(call, parent) -> str | None:
    """The name the call's permanent is known by afterwards: the seam's second
    argument, or the name a returning helper's result is bound to."""
    if call.func.attr == _SEAM:
        arg = call.args[1] if len(call.args) > 1 else None
        return arg.id if isinstance(arg, ast.Name) else None
    holder = parent.get(call)
    if isinstance(holder, (ast.Assign, ast.AnnAssign)):
        targets = holder.targets if isinstance(holder, ast.Assign) else [holder.target]
        if len(targets) == 1 and isinstance(targets[0], ast.Name):
            return targets[0].id
    return None


def _census() -> tuple[list[str], int]:
    unreviewed: list[str] = []
    examined = 0
    for path in sorted(ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parent = _parents(tree)
        module = path.relative_to(ENGINE).as_posix()
        for _func, call in _calls_of(tree, (_SEAM, *_RETURNING)):
            func = _innermost_function(call, parent)
            if func is None or func.name in (_SEAM, *_RETURNING) and call.func.attr == func.name:
                continue
            examined += 1
            if any(keyword.arg == "then" for keyword in call.keywords):
                continue
            variable = _entered_variable(call, parent)
            if variable is None:
                continue
            stmt = call
            while not isinstance(stmt, ast.stmt):
                stmt = parent[stmt]
            touching = [
                later.lineno for later in _reachable_after(stmt, parent, func)
                if variable in _names(later)
            ]
            if touching and (module, func.name) not in _REVIEWED:
                unreviewed.append(
                    f"{module}:{call.lineno} {func.name} refers to {variable!r} after "
                    f"the entry (lines {touching}) without passing then="
                )
    return unreviewed, examined


def test_every_caller_acts_on_the_entered_permanent_through_then():
    unreviewed, examined = _census()
    assert not unreviewed, "\n".join(unreviewed)
    # Measured at kg3: 38 calls of the seam and 6 of the three helpers.
    assert examined >= 40, examined


def test_every_reviewed_exception_is_still_a_caller():
    """A reviewed entry whose call site went away is a reason nobody reads."""
    callers = set()
    for path in sorted(ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parent = _parents(tree)
        for _func, call in _calls_of(tree, (_SEAM, *_RETURNING)):
            func = _innermost_function(call, parent)
            if func is not None:
                callers.add((path.relative_to(ENGINE).as_posix(), func.name))
    assert set(_REVIEWED) <= callers, sorted(set(_REVIEWED) - callers)

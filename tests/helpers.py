"""Shared test helpers.

Named ``helpers`` (no ``test_`` prefix) so pytest never collects it as a test
module. Import from here instead of copy-pasting these into each file.
"""
from pathlib import Path

from fastapi.testclient import TestClient

import web.app as web_app
import web.session_store as web_session_store
from web.app import app, store
from web.turn_steps import _begin_first_turn
from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import CardDefinition, Permanent

client = TestClient(app)

# Resolved through cards/manifest.json rather than spelled out, so the filename
# lives in one place — the registry every other reader already uses.
LEA_PATH = manifest_set_path("LEA")
# Loaded once per process; CardDefinition is immutable, so sharing is safe.
CARDS_BY_NAME = {c.name: c for c in load_cards(LEA_PATH)}


def _game(p1: PlayerState, p2: PlayerState) -> Game:
    """A two-player game with mana-cost enforcement off (the standard test rig)."""
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


def stock_libraries(game: Game, count: int = 30) -> Game:
    """Give every player whose library is empty *count* Islands to draw.

    For a test that steps whole turns and is about something else: a draw
    from an empty library loses the game (CR 704.5b), and once the game is
    over the engine's stepping goes no further (CR 104.1,
    ``engine/game_over_guard.py``) — so a test that decked a player on its
    second turn and played on was asserting about a game that had ended."""
    for player in game.players:
        if not player.library:
            player.library = [CARDS_BY_NAME["Island"]] * count
    return game


def _nosick(perm: Permanent) -> Permanent:
    """Clear summoning sickness so the permanent can attack/tap immediately."""
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# Alias used by older test files.
_no_summoning_sickness = _nosick


def _mk_card(*args, **kwargs):
    # Flexible constructor to match various test helper signatures.
    # Supported forms:
    #  - _mk_card(name, type_line)
    #  - _mk_card(name, type_line, oracle_text)
    #  - _mk_card(name, mana_cost, type_line, oracle_text)
    #  - keyword args: name=..., mana_cost=..., type_line=..., oracle_text=..., colors=(), produced_mana=()
    name = kwargs.get("name")
    mana_cost = kwargs.get("mana_cost", "")
    type_line = kwargs.get("type_line", "")
    oracle_text = kwargs.get("oracle_text", "")
    produced_mana = kwargs.get("produced_mana", ())

    if args:
        if len(args) == 1:
            name = args[0]
        elif len(args) == 2:
            name, type_line = args
        elif len(args) == 3:
            name, type_line, oracle_text = args
        else:
            name, mana_cost, type_line, oracle_text = args[:4]

    colors = kwargs.get("colors", ())
    if isinstance(colors, list):
        colors = tuple(colors)

    if name is None:
        raise TypeError("_mk_card requires at least a name")

    raw = {"name": name, "type_line": type_line}
    # Default creature stats when not provided
    if "Creature" in type_line and "power" not in raw:
        raw["power"] = str(kwargs.get("power", 2))
        raw["toughness"] = str(kwargs.get("toughness", 2))

    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=1.0 if mana_cost else 0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=produced_mana,
        raw=raw,
    )


def _mk_creature_card(name: str, power: int, toughness: int, oracle_text: str = ""):
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test", "power": str(power), "toughness": str(toughness)},
    )


def _damage_dealt(game, recipient, amount: int, source=None, combat: bool = False) -> int:
    """Run one damage event through CR 120.4 and report the damage dealt.

    The real entry point (engine/damage_events.deal_damage), which is what makes
    this usable for shield tests: it applies every effect that modifies the
    event, but *applying the result* — losing life, marking damage — is the
    caller's job, so a test can read what survived the shields without a life
    total moving or a trigger firing.
    """
    from engine.damage_events import deal_damage

    return deal_damage(
        game,
        {"recipient": recipient, "amount": amount, "source": source, "combat": combat},
    ).dealt


def resolve_stack(game, *, limit: int = 200) -> int:
    """Resolve every object on *game*'s stack, unblocking it when it stalls.

    **Use this instead of ``while game.stack: game.resolve_top_of_stack()``.**
    That loop is a latent hang, and the hang is the engine being correct.
    CR 608.2 says a resolution is not over until its last instruction is done and
    CR 117.3b says nobody receives priority until then, so an object that stopped
    to ask an interactive seat something stays on the stack and
    ``resolve_top_of_stack`` reports False for it. The bare loop then spins on a
    stack that never empties: no failure, no output, the whole suite wedged on
    one test. It costs nothing until a card in the test's pool starts asking
    something — which is why such a loop survives review, and why one of them
    stopped a run the day a trigger began announcing a target.

    **A decision is answered only while it is blocking the stack**, through the
    registry's own default path (``auto_resolve_pending_choices``, and the
    CR 614 replacement queue beside it) — the same answers an AI or headless
    seat takes. That narrowness is deliberate and was measured: a first draft
    settled the queue on every iteration and broke 41 tests, because a test that
    resolves a spell and then *inspects* what the resolution asked was reading a
    prompt the helper had answered out from under it. Draining only what blocks
    the stack is what makes this a safe swap for the bare loop.

    So this is not "settle the game". A prompt owed with an empty stack is left
    alone, and no state-based actions are performed: :func:`settle` is the
    helper that brings a game to rest.

    Returns the number of stack objects resolved. Raises rather than looping
    forever when nothing can progress — a prompt nothing defaults is a bug in the
    registry, and this names what is owed instead of timing the run out.
    """
    resolved = 0
    for _ in range(limit):
        if not game.stack:
            return resolved
        if game.resolve_top_of_stack():
            resolved += 1
            continue
        # The top is held mid-resolution: something is owed before it can
        # finish, and answering it is the only way this loop can progress.
        before = (
            len(game.pending_choices),
            len(game.pending_replacement_choices),
        )
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
        after = (
            len(game.pending_choices),
            len(game.pending_replacement_choices),
        )
        if after == before:
            raise AssertionError(
                f"the stack stopped moving with {len(game.stack)} object(s) on "
                f"it and nothing that could be answered: waiting on "
                f"{game.waiting_prompt()!r}, owed "
                f"{[c.kind for c in game.pending_choices]}"
            )
    raise AssertionError(
        f"the stack did not drain in {limit} iterations; {len(game.stack)} "
        f"object(s) left, owed {[c.kind for c in game.pending_choices]}"
    )


def _owed_prompts(game):
    """Every decision still open on either queue, oldest first: the prompt
    queue (``pending_choices``), then CR 614's (``pending_replacement_choices``).
    A choice kept queued *closed* on purpose (Word of Command's, which its
    spell finishes as it resolves) is not owed."""
    from engine.pending_choices import spec_for

    for choice in list(game.pending_choices):
        if spec_for(choice.kind).open_for(game, choice):
            yield choice
    yield from list(game.pending_replacement_choices)


def _still_owed(game, choice) -> bool:
    from engine.pending_choices import spec_for

    if any(queued is choice for queued in game.pending_replacement_choices):
        return True
    return any(queued is choice for queued in game.pending_choices) and (
        spec_for(choice.kind).open_for(game, choice)
    )


def _answer_by_default(game, choice) -> None:
    """The registry's default for one owed decision — the answer
    ``auto_resolve_pending_choices`` (or, for a CR 614 offer,
    ``auto_resolve_pending_replacement_choices``) gives it."""
    if any(queued is choice for queued in game.pending_replacement_choices):
        game.resolve_replacement_choice(
            choice.player_index, choice.default_option, kind=choice.kind
        )
    else:
        game.auto_resolve_choice(choice)


def _at_rest_report(game) -> str:
    return (
        f"stack {[item.card.name for item in game.stack]}, owed "
        f"{[(c.kind, c.player_index) for c in game.pending_choices]}"
        f" + {[(c.kind, c.player_index) for c in game.pending_replacement_choices]}"
        f", last log {game.log[-5:]}"
    )


def settle(game, *, answers=None, defaults: bool = True, limit: int = 200):
    """Bring *game* to rest: every owed prompt answered, the stack resolved,
    state-based actions performed, round again until none of the three has
    anything to do.

    Removes the two traps :func:`resolve_stack` sets, both of which cost a
    group a debugging round:

    * **An offer owed with an empty stack.** At a headless table a step's
      window resolves a trigger and pops it, and the "you may" it asks stays
      queued with nothing on the stack (Hystrodon's draw, made in the combat
      damage step) — ``resolve_stack`` returns at once and the board reads as
      though the trigger did nothing. This answers it.
    * **No state-based actions.** ``resolve_stack`` resolves through
      ``resolve_top_of_stack``, so a creature a resolution dealt lethal damage
      to is still on the battlefield afterwards. This resolves through the
      engine's own unit of play (``Game.resolve_next_object``: the resolution
      and CR 704.3's check after it, in one trigger window, holding the object
      for an answer where the table does, ``holds_for_answers``) and checks
      again whenever the stack is empty (CR 117.5).

    A prompt is answered before the next object resolves (CR 608.2: the
    resolution that asked is not over until it is), oldest first:

    * by ``answers[choice.kind](game, choice)`` when *answers* names its kind
      — a callable that gives the answer through the engine's own funnel
      (``lambda game, c: game.confirm_optional_pay(c.player_index, accept=True)``);
      raises if the choice is still owed afterwards (the answer was refused);
    * otherwise by its registry default (``auto_resolve_choice``, the answer an
      AI or headless seat takes) — **an interactive seat's prompt included**,
      which is ``resolve_stack``'s other surprise, stated here instead.

    ``defaults=False`` answers only what *answers* names and **stops at the
    first other prompt the game waits on**, returning it, so a test can read
    what was asked; a notification nothing waits on (``hand_reveal``) is left
    queued and does not stop it. Otherwise returns None. A table with a
    ``prompt_driver`` has its prompts handed to the driver first.

    Steps no step: a step's turn-based actions and the walk through combat are
    :func:`drive_combat`'s. Stops quietly once the game is over (CR 104.1).
    Raises, naming what is owed, when the stack stops moving with nothing left
    to answer, and when *limit* rounds pass without the game coming to rest.
    """
    from engine.pending_choices import spec_for

    answers = dict(answers or {})
    for _ in range(limit):
        if game.is_game_over():
            return None
        if game.drive_owed_prompts():
            continue
        owed = None
        for choice in _owed_prompts(game):
            if choice.kind in answers or defaults or spec_for(choice.kind).holds_priority:
                owed = choice
                break
        if owed is not None:
            if owed.kind in answers:
                answers[owed.kind](game, owed)
                if _still_owed(game, owed):
                    raise AssertionError(
                        f"the answer given for {owed.kind!r} (seat "
                        f"{owed.player_index}) left it owed: {_at_rest_report(game)}"
                    )
            elif defaults:
                _answer_by_default(game, owed)
            else:
                return owed
            continue
        if game.stack:
            if not game.resolve_next_object(pause_for_choices=game.holds_for_answers()):
                if game.is_game_over():
                    return None
                raise AssertionError(
                    "the stack stopped moving with nothing left to answer: "
                    f"waiting on {game.waiting_prompt()!r}; {_at_rest_report(game)}"
                )
            continue
        # CR 117.5: the check a player makes before receiving priority with
        # the stack empty — which may put a trigger there, or ask something.
        if game.check_state_based_actions() or game.stack:
            continue
        return None
    raise AssertionError(
        f"the game did not come to rest in {limit} rounds: {_at_rest_report(game)}"
    )


def entering_or_present(game, seat: int, name: str):
    """The permanent named *name* entering under *seat* — **on its way** while
    an "as it enters" choice is owed (CR 614.12a: at a table that holds for
    answers the permanent is on no battlefield until the answer,
    ``engine/entry_awaiting.py``), or on the battlefield once it is there.

    For a test that casts a chooser at an interactive seat and wants the
    permanent before answering its prompt: reading it off the battlefield then
    finds nothing."""
    for record in getattr(game, "entries_in_progress", ()) or ():
        if record.controller_index == seat and record.permanent.card.name == name:
            return record.permanent
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


#: Set to anything but ``""`` or ``"0"`` and every census that samples through
#: :func:`stable_sample` examines its whole population instead — what the full
#: pass (``pytest --full``, the promotion gate's run) sets. An environment
#: variable rather than a ``full`` mark because the census still runs in the
#: quick pass, on its sample; the whole pool is what a promotion is for.
from tests.passes import FULL_CENSUS_ENV  # noqa: E402


def full_census() -> bool:
    """Whether this run was asked for every row (:data:`FULL_CENSUS_ENV`)."""
    import os

    return os.environ.get(FULL_CENSUS_ENV, "") not in ("", "0")


def stable_digest(label: str) -> int:
    """A digest of *label* that is the same in every process and on every
    pool: ``zlib.crc32`` of its UTF-8, never the salted built-in ``hash()``."""
    import zlib

    return zlib.crc32(label.encode("utf-8"))


def stable_sample(label: str, every: int) -> bool:
    """Whether *label* — a card's name, or a name with an ability's ordinal —
    is in a census's one-in-*every* sample.

    **By what the row is, never by where it sits.** A census that took every
    Nth card of a sorted, filtered pool re-sampled whenever the pool moved: a
    card supported, a set promoted or ingested, and every row behind it shifted
    one place, so a finding flickered in and out across merges that never
    touched it (Shaman's Trance, at Judgment) and a floor measured on one pool
    failed on the next. A digest of the label keeps each row's membership a
    fact about the row: growing the pool only *adds* rows, at the same rate.

    Every row is in the sample when *every* is 1 or :func:`full_census` is set.
    """
    if every <= 1 or full_census():
        return True
    return stable_part(label, every) == 0


def stable_part(label: str, parts: int) -> int:
    """Which of *parts* digest classes *label* is in; :func:`stable_sample`
    keeps class 0.

    For a census too long to be one test even in the full pass: it runs each
    class as a test of its own, so every row is still examined and xdist's
    workers share them (``tests/regressions/test_ody_w2g2_zone_cast_census.py``).
    """
    return stable_digest(label) % parts


def action_slots(game, action) -> list:
    """Where an AI action's targets stand **now**, in the action's order: each
    permanent id's slot on its controller's battlefield (None for one that has
    left), or each named graveyard card's place in its pile.

    An action names a permanent by id and a graveyard card by its place
    (``engine/target_keywords``); a test that asserts *which* object it named
    by where that object sits reads it here, always as a list.
    """
    graveyard = list(getattr(action, "target_graveyard_indices", None) or ())
    if graveyard:
        return graveyard
    slots = []
    for permanent_id in getattr(action, "target_permanent_ids", None) or ():
        permanent = game.permanent_by_id(permanent_id) if isinstance(permanent_id, int) else None
        slots.append(None if permanent is None else game.battlefield_index_of(permanent))
    return slots


def action_target(game, action):
    """The one permanent an AI action names by id, or None."""
    ids = [pid for pid in (getattr(action, "target_permanent_ids", None) or ()) if isinstance(pid, int)]
    return game.permanent_by_id(ids[0]) if len(ids) == 1 else None


def _get(all_cards, name: str):
    return next(card for card in all_cards if card.name == name)

def _pass_priority(session_id: str, seat: int):
    session = store.get(session_id)
    if seat == 1 and seat not in session.joined_seats and session.mode == "human_vs_human":
        client.post(f"/api/sessions/{session_id}/join", json={"guest_name": "Joiner"})
    return client.post(
        f"/api/sessions/{session_id}/action",
        json={"seat": seat, "action": "pass_priority"},
    )


def _resolve_top_stack(session_id: str, first_pass_seat: int):
    first = _pass_priority(session_id, first_pass_seat)
    assert first.status_code == 200
    second = _pass_priority(session_id, 1 - first_pass_seat)
    assert second.status_code == 200
    return second


def seat_plays_first(session_id: str, seat: int = 0):
    """*seat* takes turn 1 of a web session created without the pregame, for
    a test that means "this seat acts first" and is not about the coin flip.

    The no-pregame first deal plays first whoever its flip names
    (``SessionStore._begin_pregame``), and the route that dealt has already
    begun that seat's turn 1 (``turn_steps._begin_first_turn``). When the flip
    went to the other seat, this begins turn 1 again for *seat* through the
    same function — its untap, upkeep and draw step (the draw skipped, CR
    103.8a), then its precombat main phase with its priority — so the session's
    turn, the engine's active player and priority all name *seat*, and turn 1
    is that seat's first turn (``Game.seat_turn_counts``). A seed chosen for
    its flip would say the same thing silently, and a reseed deals other decks.

    Call it straight after creating (and joining) the session, before the
    test builds its board: a board already there is untapped and its upkeep
    run, as turn 1's would be. Returns the session.
    """
    session = store.get(session_id)
    if session.current_turn == seat:
        return session
    game = session.game
    assert session.pregame_phase is None and game.turn == 1, (
        "seat_plays_first sets up turn 1 of a game dealt without the pregame"
    )
    session.current_turn = seat
    game.seat_turn_counts.clear()
    session.first_turn_owed = True
    _begin_first_turn(session)
    assert (game.active_player_index, game.priority_player_index) == (seat, seat), (
        "turn 1's beginning phase stopped before its main phase"
    )
    return session


def app_js_function_body(name: str) -> str:
    """The source of one top-level ``function name(...) { ... }`` in app.js.

    Read as text for the reason ``tests/ui/test_cast_target_kinds.py`` gives:
    ``app.js`` is DOM-coupled and bare ``node`` cannot load it, and the thing
    being checked is which cascade calls what — which is the real answer rather
    than a paraphrase of it. The closing brace is the first one in column 0,
    which is how every top-level function in that file ends.

    Here rather than in one of the two ``tests/ui`` modules that ask it, because
    both do: the chosen-source regression reads the two walks that send a cast,
    and the target-kind sweep reads the same walks to ask whether every kind
    that requests a source reaches the stage that collects one. A second copy is
    how the two would come to disagree about what "the body of a walk" means.
    """
    import re

    source = (
        Path(__file__).resolve().parents[1] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"^(?:async )?function " + re.escape(name) + r"\([^)]*\)\s*\{\n(.*?)^\}$",
        source, re.S | re.M,
    )
    assert match is not None, f"{name} is gone or was renamed"
    return match.group(1)


_APP_JS_DRIVER = r'''
const fs = require("fs");
const CR = String.fromCharCode(13);
const src = fs.readFileSync(process.argv[2], "utf8").split(CR).join("");
function grab(name) {
  const at = src.indexOf("\nfunction " + name + "(");
  const asyncAt = src.indexOf("\nasync function " + name + "(");
  const i = at >= 0 ? at : asyncAt;
  if (i < 0) throw new Error("app.js no longer defines " + name);
  const end = src.indexOf("\n}\n", i);
  return src.slice(i, end + 2);
}
const INPUT = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
__PRELUDE__
eval(__NAMES__.map(grab).join("\n") + ";globalThis.__run = async (INPUT) => {" + __BODY__ + "}");
globalThis.__run(INPUT).then(
  (out) => process.stdout.write(JSON.stringify(out === undefined ? null : out)),
  (err) => { process.stderr.write(String(err && err.stack || err)); process.exit(1); },
);
'''


def run_app_js(functions, body: str, payload=None, *, prelude: str = "",
               scripts: tuple[str, ...] = ("app.js",)):
    """Run *body* in bare node with the named top-level functions of
    ``app.js`` in scope, and return what it returns.

    *scripts* names the ``web/static`` files the functions are lifted from, in
    page order: the page loads ``battlefield-canvas.js`` before ``app.js``, and
    a client function can call a helper the canvas file defines (the face-down
    and library-top readers), so a test of it lifts from both.

    ``app.js`` is one DOM-bound script and cannot be loaded whole, so the
    functions under test are lifted out by name — the real source, not a
    paraphrase — and everything they reach for that touches the page is
    declared by *prelude* (plain JavaScript: the module state they close over,
    and stubs that record what they were handed). *body* is the body of an
    async function taking ``INPUT`` (*payload*, round-tripped through JSON);
    its return value comes back parsed.

    Here because several ``tests/ui`` modules ask a client function what it
    decides for a payload the server really sent; each used to carry its own
    copy of this driver.
    """
    import json
    import subprocess
    import tempfile

    static = Path(__file__).resolve().parents[1] / "web" / "static"
    driver = (
        _APP_JS_DRIVER
        .replace("__PRELUDE__", prelude)
        .replace("__NAMES__", json.dumps(list(functions)))
        .replace("__BODY__", json.dumps(body))
    )
    with tempfile.TemporaryDirectory(prefix="app-js-") as folder:
        driver_path = Path(folder) / "driver.js"
        payload_path = Path(folder) / "input.json"
        source_path = Path(folder) / "source.js"
        driver_path.write_text(driver, encoding="utf-8")
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        # One source the driver greps, the scripts joined in page order; a
        # newline between them so the last function of one still ends "\n}\n".
        source_path.write_text(
            "\n".join((static / name).read_text(encoding="utf-8") for name in scripts) + "\n",
            encoding="utf-8",
        )
        done = subprocess.run(
            ["node", str(driver_path), str(source_path), str(payload_path)],
            capture_output=True, text=True, encoding="utf-8",
        )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def declare_attack(game, attacker_seat: int, *, blocks: "dict | None" = None) -> list:
    """Put *game* in *attacker_seat*'s combat with every creature that seat
    controls attacking the other seat, and *blocks* (``{blocker slot: attacker
    slot}``; none by default) declared: the declare-blockers step, with the
    damage still to be dealt. Returns the attacking permanents.

    The board a combat trick is *for*. A seat no longer casts a Fog, a shield
    or a pump in a main phase where nothing it does outlasts the turn, so a
    test of what such a spell names, or of what is paid for it, needs the
    fight it decides to be on the table.
    """
    defender_seat = 1 - attacker_seat
    game.active_player_index = attacker_seat
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [
        slot for slot, permanent in enumerate(game.players[attacker_seat].battlefield)
        if permanent.is_creature and not permanent.tapped
    ]
    for slot in slots:
        _nosick(game.players[attacker_seat].battlefield[slot])
    ok, why = game.declare_attackers(attacker_seat, slots, defending_player_index=defender_seat)
    assert ok, why
    attackers = [game.players[attacker_seat].battlefield[slot] for slot in slots]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step
    ok, why = game.declare_blockers(defender_seat, dict(blocks or {}))
    assert ok, why
    return attackers


def _combat_waits_on(game) -> str:
    """What a combat step that did not move is waiting for, in words a test
    author can act on."""
    step, active = game.current_step, game.active_player_index
    if step == "declare_attackers" and not game.combat_attackers_locked:
        return (
            f"seat {active}'s attack declaration (CR 508.1): game.declare_attackers, "
            "or tests.helpers.declare_attack"
        )
    if step == "declare_blockers" and not game.combat_blockers_locked:
        if game.is_camouflage_active():
            return "the defender's Camouflage piles (game.assign_camouflage_piles)"
        seat = game._pending_block_declarer()
        return (
            f"seat {seat}'s block declaration (CR 509.1): game.declare_blockers("
            f"{seat}, {{blocker slot: attacker slot}}), or declare_attack(blocks=...)"
        )
    if step == "combat_damage" and not game.combat_damage_resolved:
        return (
            "a combat damage assignment an interactive seat makes (CR 510.1c-d, "
            f"702.19b; trample asks {game.trample_assignments_to_ask()}): "
            "game.resolve_combat_damage(seat, attacker_damage=...)"
        )
    if game.step_held_open():
        return f"the step held open on {game.waiting_prompt()!r}"
    return "nothing this helper can name"


def drive_combat(
    game, *, through: str = "end_of_combat", answers=None, defaults: bool = True,
    limit: int = 30,
):
    """Walk *game*'s combat forward from wherever it is until the step named
    *through* has ended, settling each step before it is left. Typically called
    after :func:`declare_attack`; from a main phase it begins the combat phase.

    **The default carries through the end of combat step**, so combat is over
    (CR 511.3) when it returns: creatures are no longer attacking or blocking
    and every until-end-of-combat effect has ended (CR 511.2). The "at end of
    combat" triggers — Time Elemental's delayed sacrifice, Wall of Nets, a
    Basilisk's destruction — fire as that step *begins* (CR 511.2), so they
    are on the stack the moment a drive arrives there, and every stop at or
    after the arrival resolves them.

    ``through="combat_damage"`` stops on arriving in the end of combat step,
    with the damage dealt, every trigger it set off resolved, and the end of
    combat triggers resolved too — but with the creatures still in combat,
    because the step has not ended. The engine
    deals combat damage as the combat damage step begins (CR 510.1 and 510.2
    are turn-based actions), so ``through="declare_blockers"`` stands *in* the
    combat damage step with the damage already dealt.

    Each step is settled (:func:`settle`, with *answers* and *defaults*) before
    it is left, and the damage step is entered with ``allow_damage_skip=False``
    — the engine's own road for a player who holds priority there — so an offer
    a step's trigger makes is answered in that step. At a headless table the
    engine leaves a step without waiting for one (``window_left_unfinished``
    is False there by design), which is how Hystrodon's "you may draw" was
    still owed in the postcombat main phase.

    The stepping is the engine's (``advance_combat_phase``); this only decides
    when to stop. The declarations stay the test's: a step waiting on attackers,
    blockers or a damage assignment raises naming what it waits on. Returns the
    prompt it stopped at under ``defaults=False`` (see :func:`settle`), else
    None; stops quietly once the game is over (CR 104.1).
    """
    steps = list(game._phase_steps("combat"))
    if through not in steps:
        raise ValueError(f"through={through!r} is not a combat step: {steps}")
    goal = steps.index(through)

    def position():
        if game.current_turn_phase != "combat" or game.current_step not in steps:
            return None
        return steps.index(game.current_step)

    entered = position() is not None
    if not entered and game._next_phase_after(game.current_turn_phase) != "combat":
        # ``advance_combat_phase`` begins a combat from anywhere it is asked
        # to, so a second drive after the first had finished would start a
        # combat phase the turn never had.
        raise ValueError(
            f"not in combat, and the turn has no combat phase next after "
            f"{game.current_turn_phase}"
        )
    furthest = position() if entered else -1
    for _ in range(limit):
        owed = settle(game, answers=answers, defaults=defaults)
        if owed is not None or game.is_game_over():
            return owed
        here = position()
        if here is None:
            if entered:
                return None
        else:
            # A step earlier than one already reached is a *second* combat
            # phase (Relentless Assault): the one this was driving is over.
            if here < furthest or here > goal:
                return None
            furthest = here
        before = (
            game.turn, game.current_turn_phase, game.current_step, game.held_step,
            game.combat_attackers_locked, game.combat_blockers_locked,
            game.combat_damage_resolved, len(game.stack), len(game.log),
        )
        game.advance_combat_phase(allow_damage_skip=False)
        entered = True
        after = (
            game.turn, game.current_turn_phase, game.current_step, game.held_step,
            game.combat_attackers_locked, game.combat_blockers_locked,
            game.combat_damage_resolved, len(game.stack), len(game.log),
        )
        if after == before and not any(True for _ in _owed_prompts(game)):
            raise AssertionError(
                f"combat stopped in {game.current_step} waiting on "
                f"{_combat_waits_on(game)}"
            )
    raise AssertionError(
        f"combat did not get through {through} in {limit} steps; it is in "
        f"{game.current_turn_phase}/{game.current_step}"
    )


def combat_ids(game, body: dict) -> dict:
    """*body* — a combat action's request, written by battlefield slot — with
    each slot field sent as its by-id twin (``web.actions.COMBAT_ID_FIELDS``:
    ``attacker_indices`` → ``attacker_ids``, ``blocker_pairs`` →
    ``blocker_pairs_by_id`` …), every slot read off *game*'s board as it stands
    when the request is built.

    The wire refuses the slot fields from a client (CR 400.7: a slot names
    whatever sits in it when it is read). This is the test-side twin of what
    the browser does with a draft it keeps by slot (``combatIdKeyed`` in
    ``app.js``): the test reasons about the board by slot, and the request
    names creatures by id. Each slot is read on the battlefield the engine
    reads that position on — an attacker on the active player's, a blocker in
    a damage map on that of the player its attacker attacks, a declaration's
    blockers on the defending player's, a pile on the acting seat's. A slot
    with nothing in it is sent as id 0, which names nothing (a 404).
    """
    from web.actions import COMBAT_ID_FIELDS

    body = dict(body)
    active = game.active_player_index

    def id_at(seat, slot):
        permanent = game.permanent_at(seat, int(slot)) if isinstance(seat, int) else None
        return permanent.permanent_id if permanent is not None else 0

    def attacker(slot):
        return id_at(active, slot)

    def blocker_seat(attacker_slots):
        seats = {game._combat_seat_of_blocker(int(a)) for a in attacker_slots}
        return seats.pop() if len(seats) == 1 else game.combat_defending_player_index

    def listed(value):
        return value if isinstance(value, list) else [value]

    def declaring_seat():
        seat = body.get("seat")
        if seat in game.combat_defending_players():
            return seat
        pending = body.get("target_seat")
        return pending if pending is not None else game._pending_block_declarer()

    convert = {
        "attacker_indices": lambda v: [attacker(a) for a in v],
        "bands": lambda v: [[attacker(a) for a in band] for band in v],
        "attacker_planeswalker_ids": lambda v: {attacker(a): w for a, w in v.items()},
        "blocker_pairs": lambda v: {
            id_at(declaring_seat(), b): [attacker(a) for a in listed(a_s)] for b, a_s in v.items()
        },
        "attacker_damage": lambda v: {
            attacker(a): {id_at(blocker_seat([a]), b): n for b, n in split.items()}
            for a, split in v.items()
        },
        "banding_damage": lambda v: {
            attacker(a): {id_at(blocker_seat([a]), b): n for b, n in split.items()}
            for a, split in v.items()
        },
        "blocker_damage": lambda v: {id_at(blocker_seat([a]), b): attacker(a) for b, a in v.items()},
        "blocker_damage_split": lambda v: {
            id_at(blocker_seat(split), b): {attacker(a): n for a, n in split.items()}
            for b, split in v.items()
        },
        "piles": lambda v: {id_at(body.get("seat"), c): side for c, side in v.items()},
        "camouflage_piles": lambda v: {id_at(body.get("seat"), c): p for c, p in v.items()},
    }
    by_id = {slot: field for field, slot in COMBAT_ID_FIELDS.items()}
    assert set(convert) == set(by_id), "a combat slot field this helper cannot convert"
    for slot_field, field in by_id.items():
        if body.get(slot_field) is not None:
            body[field] = convert[slot_field](body.pop(slot_field))
    return body

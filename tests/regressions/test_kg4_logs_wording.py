"""The log says what a player reads — kg4's "log and wire leftovers", by class.

Each part is a census by shape over every ``*.log.append`` call in ``engine/``
and ``web/`` (an AST walk, so a line split over several f-string parts is read
whole), validated backwards on the kg4 base, plus a board driven through the
real entry points:

* no log line prints an engine slot number ("Rookie Mistake: slot 2 is no
  longer a legal target" — seven lines on the base);
* no log line names a card by a literal it did not read off the object it is
  about ("Camouflage matched …", "(Lich)", "(Jade Monolith)" — 30 lines on the
  base, a text-keyed effect named after the card its sentence was first
  printed on whatever printed it);
* a P/T modification is written as the card prints it ("-1/-0", never the
  "-1/+0" thirteen ``{p:+}/{t:+}`` sites wrote — ``pt.pt_change_text``);
* a held resolution ends in one line, not "resolved and moved to graveyard"
  and then "finished resolving";
* two spells of one name on the stack read apart in a prompt that offers both
  (Hindering Touch's storm copy was offered "Shock" and "Shock").
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.pt import pt_change_text
from tests.helpers import _nosick, resolve_stack
from web.prompt_board import _retarget_choice, _trigger_target
from web.prompt_registry import PromptContext

ROOT = Path(__file__).resolve().parents[2]
_C = {card.name: card for card in load_catalog()}


# ---------------------------------------------------------------------------
# The census over the log's format sites
# ---------------------------------------------------------------------------

def _log_calls():
    """``(path, call)`` for every ``<x>.log.append/extend/insert(...)`` in the
    engine and the web layer."""
    for path in sorted((ROOT / "engine").rglob("*.py")) + sorted((ROOT / "web").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in {"append", "extend", "insert"}:
                continue
            value = node.func.value
            if (isinstance(value, ast.Attribute) and value.attr == "log") or (
                isinstance(value, ast.Name) and value.id == "log"
            ):
                yield path, node


def _format_text(node) -> list[str]:
    """The literal text a log argument is written with: the constant parts of
    its f-strings and plain strings, joined by ``+`` or implicit concatenation —
    never a string passed to a call inside it (a dict key, a fallback)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [part.value for part in node.values if isinstance(part, ast.Constant)]
    if isinstance(node, ast.BinOp):
        return _format_text(node.left) + _format_text(node.right)
    if isinstance(node, ast.IfExp):
        return _format_text(node.body) + _format_text(node.orelse)
    return []


def _log_texts():
    found = []
    for path, call in _log_calls():
        for argument in call.args:
            text = " ".join(_format_text(argument))
            found.append((path.relative_to(ROOT).as_posix(), call.lineno, text, call))
    return found


def test_no_log_line_prints_an_engine_slot_number():
    """"slot N" was the handler's number for a printed target, and nothing a
    player sees calls it that. Seven lines on the base (pump.py's three,
    keywords.py's four); the targets are named "its first target, <card>"
    now (``handlers._targets.target_ordinal``)."""
    texts = _log_texts()
    assert len(texts) >= 2_000, f"the census read only {len(texts)} log calls"
    slotted = [
        (path, line, text) for path, line, text, _call in texts
        if re.search(r"\bslot\b", text)
    ]
    assert not slotted, slotted


def _pool_names() -> set[str]:
    names: set[str] = set()
    for card in load_catalog():
        names.add(card.name)
        names.update(card.name.split(" // "))
    return names


#: Words that are a card's name *and* a word the rules use on their own: a
#: basic land type a permanent becomes ("became a Swamp"). Naming one is not
#: naming the card.
_TYPE_WORDS = {"Swamp", "Island", "Forest", "Plains", "Mountain"}


def test_no_log_line_names_a_card_it_did_not_read_off_an_object():
    """A text-keyed effect is every card that prints its sentence, so a log
    line naming the exemplar ("drew 2 card(s) instead (Lich)", "Camouflage
    matched …", "Damage to X redirected (Jade Monolith)") names a card that may
    not be there. 30 literal names on the kg4 base; each line now names the
    object in scope — the permanents the effect's ``sources`` reader finds,
    the shield's granting card, the resolving card — or says nothing."""
    names = _pool_names()
    texts = _log_texts()
    assert len(texts) >= 2_000, f"the census read only {len(texts)} log calls"
    literal = []
    for path, line, text, _call in texts:
        words = re.findall(r"[A-Za-z0-9'\-,!]+", text)
        for start in range(len(words)):
            for end in range(start + 1, min(len(words), start + 7) + 1):
                phrase = " ".join(words[start:end]).strip(",")
                if len(phrase) >= 4 and phrase in names and phrase not in _TYPE_WORDS:
                    literal.append((path, line, phrase))
    assert not literal, literal


def test_no_format_site_signs_a_pt_modification_half_by_half():
    """``{power:+}/{toughness:+}`` writes a zero half as "+0" whatever its
    partner is, so a printed -1/-0 logged as "-1/+0". Thirteen sites on the
    base, plus Berserk's and rampage's own spellings; one formatter now."""
    offenders = []
    users = 0
    for folder in ("engine", "web", "scripts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            users += source.count("pt_change_text(")
            for number, line in enumerate(source.splitlines(), 1):
                if re.search(r":\+d?\}\s*/\s*\{[^}]*:\+", line) and "def pt_change_text" not in line:
                    if path.name == "pt.py":
                        continue  # the formatter itself
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    assert not offenders, offenders
    assert users >= 16, f"pt_change_text is called from only {users} places"


def test_the_formatter_follows_the_pools_own_convention():
    """Every printed modification in the pool signs a zero half as its partner
    is signed — read off the card data, so the convention the formatter keeps
    is the one the cards keep."""
    printed: set[str] = set()
    for path in sorted((ROOT / "cards").glob("*.json")):
        if path.name == "manifest.json":
            continue
        text = path.read_text(encoding="utf-8").replace("−", "-")
        printed.update(re.findall(r"[+-]\d+/[+-]\d+", text))
    assert len(printed) >= 20
    for written in printed:
        power, toughness = (int(half) for half in written.split("/"))
        if power and toughness:
            continue
        assert pt_change_text(power, toughness) == written, written
    assert pt_change_text(-1, 0) == "-1/-0"
    assert pt_change_text(0, -2) == "-0/-2"
    assert pt_change_text(2, 0) == "+2/+0"
    assert pt_change_text(0, 0) == "+0/+0"
    assert pt_change_text(1, -1) == "+1/-1"


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------

def _table(*, hand=(), theirs_hand=(), mine=(), theirs=(), interactive=()):
    game = Game(players=[
        PlayerState(name="P1", hand=[_C[n] for n in hand], library=[_C["Forest"]] * 8),
        PlayerState(name="P2", hand=[_C[n] for n in theirs_hand], library=[_C["Forest"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _nosick(Permanent(card=_C[name]))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    game._settle()
    return game, placed


def test_a_two_target_pump_names_the_target_it_dropped():
    """Rookie Mistake's first target leaves with the spell on the stack: the
    second still shrinks, and the log names the dropped one as the card does
    ("its first target") rather than as the handler numbered it."""
    game, placed = _table(hand=["Rookie Mistake"], mine=["Grizzly Bears"], theirs=["Hill Giant"])
    mine, theirs = placed[0][0], placed[1][0]
    assert game.queue_from_hand(
        0, "Rookie Mistake", target_player_index=0,
        target_permanent_index=[0, 0],
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    ).supported
    game.remove_from_battlefield(mine)
    resolve_stack(game)

    assert "Rookie Mistake: its first target is no longer a legal target" in game.log
    assert f"Rookie Mistake gives Hill Giant {pt_change_text(-2, 0)} until end of turn" in game.log
    assert not any("slot" in line for line in game.log)
    assert theirs.effective_power == 1


def test_a_printed_minus_n_minus_zero_logs_as_printed():
    """Shrink: "Target creature gets -5/-0 until end of turn." The lowering
    negates a zero into a zero, and the log wrote the sign of what was left."""
    game, placed = _table(hand=["Shrink"], theirs=["Craw Wurm"])
    wurm = placed[1][0]
    assert game.queue_from_hand(0, "Shrink", target_permanent_ids=[wurm.permanent_id]).supported
    resolve_stack(game)

    assert wurm.effective_power == 1
    assert any("-5/-0 until end of turn" in line for line in game.log), game.log[-4:]
    assert not any("-5/+0" in line for line in game.log)


def _closing_lines(game, name):
    return [
        line for line in game.log
        if line.startswith(name) and ("resolv" in line or "moved to graveyard" in line)
    ]


def test_a_held_spell_ends_in_one_line():
    """Mind Rot's discard is owed by an interactive seat, so the spell is held
    (CR 608.2) and binned at the last answer (CR 608.2n). Its end used to read
    twice: "resolved and moved to graveyard", then "finished resolving"."""
    game, _ = _table(
        hand=["Mind Rot"], theirs_hand=["Opt", "Island", "Swamp"], interactive=(0, 1),
    )
    assert game._cast_onto_stack(0, "Mind Rot", target_player_index=1).supported
    game.priority_player_index = 0
    game.pass_priority(0)
    assert game.pass_priority(1) == "awaiting_choice"
    assert game.resolve_pending_choice("discard", 1, hand_indices=[0, 1], to_library=False)

    assert game.stack == []
    assert _closing_lines(game, "Mind Rot") == [
        "Mind Rot is resolving, awaiting a choice",
        "Mind Rot finished resolving and moved to graveyard",
    ]


def test_a_spell_held_behind_a_search_ends_in_one_line():
    """The other road to the bin: a suspending prompt (a search) holds the
    finish step back inside ``run_resumable``, and the object stays held."""
    game, _ = _table(hand=["Demonic Tutor"], interactive=(0,))
    assert game._cast_onto_stack(0, "Demonic Tutor").supported
    game.priority_player_index = 0
    game.pass_priority(0)
    game.pass_priority(1)
    owed = game.pending_choice_of("search_library")
    assert owed is not None
    game.take_choice_default(owed)

    assert game.stack == []
    assert _closing_lines(game, "Demonic Tutor")[-1] == (
        "Demonic Tutor finished resolving and moved to graveyard"
    )
    assert "Demonic Tutor finished resolving" not in game.log
    assert "Demonic Tutor resolved and moved to graveyard" not in game.log


def test_a_spell_nothing_held_still_resolves_in_its_own_words():
    game, _ = _table(hand=["Shock"])
    assert game.queue_from_hand(0, "Shock", target_player_index=1).supported
    resolve_stack(game)
    assert "Shock resolved and moved to graveyard" in game.log
    assert not any("finished resolving" in line for line in game.log)


def _ctx(game, seat):
    return PromptContext(
        game=game, viewer_seat=seat,
        serialize_card=lambda card: {"name": card.name},
        seat_type=lambda _seat: "human",
    )


def test_two_shocks_on_the_stack_read_apart_in_a_storm_copys_offer():
    """Hindering Touch's storm copy may be re-aimed at another spell
    (CR 702.40a, 707.10): two Shocks one player cast are two options, and the
    person choosing between them is told whose each is and where it is — they
    were offered as "Shock" and "Shock"."""
    game, _ = _table(
        hand=["Dark Ritual", "Hindering Touch"],
        theirs_hand=["Shock", "Shock", "Lightning Bolt"],
        interactive=(0,),
    )
    assert game.queue_from_hand(0, "Dark Ritual").supported
    resolve_stack(game)
    for name in ("Shock", "Shock", "Lightning Bolt"):
        assert game.queue_from_hand(1, name, target_player_index=0).supported
    # The Bolt, the last of the three: the Touch and each copy aim at it.
    bolt = game.stack.index(next(item for item in game.stack if item.card.name == "Lightning Bolt"))
    assert game.queue_from_hand(0, "Hindering Touch", target_stack_index=bolt).supported
    assert game.resolve_top_of_stack()
    owed = game.pending_choice_of("retarget_choice")
    assert owed is not None and owed.player_index == 0

    names = [option["name"] for option in owed.data["options"]]
    assert names[0] == "Keep the original's target"
    assert sorted(names[1:]) == ["P1's Hindering Touch", "P2's Shock", "P2's Shock"], names

    payload = _retarget_choice(_ctx(game, 0), [owed])
    spells = [option for option in payload["options"] if option["kind"] == "stack"]
    assert len(spells) == 3, payload
    for option in spells:
        assert isinstance(option.get("stack_index"), int)
    assert sorted(option["seat"] for option in spells) == [0, 1, 1]
    shown = [option["name"] for option in payload["options"]]
    assert len(shown) == len(set(shown)), shown
    assert any(name.startswith("P2's Shock (") and name.endswith(" from the top)") for name in shown)


def test_two_spells_of_one_name_and_one_controller_say_where_each_is():
    """The same two Shocks offered to a trigger that targets a spell: the
    names match (one controller, neither a copy), so each also says where on
    the stack it sits — the moment the person is choosing in."""
    from web.prompt_board import _told_apart_on_the_stack

    entries = _told_apart_on_the_stack([
        {"kind": "stack", "stack_index": 0, "name": "P2's Shock"},
        {"kind": "stack", "stack_index": 1, "name": "P2's Shock"},
        {"kind": "stack", "stack_index": 2, "name": "P1's Giant Growth"},
        {"kind": "permanent", "name": "P2's Grizzly Bears"},
    ])
    assert [entry["name"] for entry in entries] == [
        "P2's Shock (top of the stack)",
        "P2's Shock (2nd from the top)",
        "P1's Giant Growth",
        "P2's Grizzly Bears",
    ]
    assert _trigger_target is not None  # the renderer that calls it


def test_the_census_saw_the_card_data():
    """A floor on the P/T census's other half: the card files were read."""
    manifest = json.loads((ROOT / "cards" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("sets")

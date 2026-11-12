"""Census: every read of what a spell on the stack **says** goes through
``text_changes.spell_text_card``.

A spell's ``StackItem.card`` is two things at once: the object every reader
asks what it says (its program, its targets, its colour and creature types),
and the physical card that goes to a graveyard, a hand or the battlefield as it
leaves the stack. A text change on a spell ("Change the text of target spell
or permanent", CR 612) is recorded beside it (``StackItem.text_change_effects``)
and folded by ``spell_text_card``; a reader that asks ``item.card`` for text
reads the printed words, and the change is silently ignored there — nothing
crashes, the spell just plays as if nobody had changed it.

So the line is drawn in the source, statically, over ``engine/`` and ``web/``:

* every raw ``.card`` read of a stack object (by the names a stack object goes
  by, ``STACK_NAMES``) is either an **identity** read — its name (CR 612.2: a
  text change never changes a name), a card type no text change in this pool
  reaches, a comparison, a zone move — or listed in ``PRINTED_CARD_READS``
  with why the printed card is the right answer there;
* every function in ``READS_THROUGH_SPELL_TEXT_CARD`` — the sites that read a
  resolving or waiting spell's text — calls ``spell_text_card``.

Validated backwards on the base this round started from (``e7a41c0e``): both
halves fail there (no reader exists, and the text sites read ``item.card``).
The census is name-scoped: a stack object held under a name outside
``STACK_NAMES`` is not seen, which the floors below keep honest about how much
was examined.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.source_index import source_tree

ROOT = Path(__file__).resolve().parents[2]

#: The names a stack object goes by in ``engine/`` and ``web/``. Some also name
#: other things somewhere ("entry", "obj", "spell"); those reads are listed in
#: ``PRINTED_CARD_READS`` with that reason.
STACK_NAMES = frozenset({
    "item", "top", "stack_item", "spell_item", "target_item", "stack_target",
    "cast_item", "held", "countered", "spell_obj", "target_spell", "resolving",
    "existing", "waiting", "it", "found", "obj", "entry", "other", "spell",
})

#: Two modules where ``target`` is the targeted stack object (a counter's).
STACK_NAMES_BY_FILE = {
    "engine/handlers/stack.py": frozenset({"target"}),
    "engine/mixins/stack/choices/payments.py": frozenset({"target"}),
}

#: Attributes that hold a stack object (``context.stack_target.card``).
STACK_ATTRS = frozenset({"stack_target", "target_stack_item", "cast_item"})

#: What a read may do with the printed card without asking what the spell
#: says: its name (CR 612.2), a card type (none of the three vocabularies a
#: text change in this pool swaps — colour words, basic land types, creature
#: types — is a card type), its mana value or cost (CR 612.1: rules text and
#: type line).
IDENTITY_ATTRS = frozenset({"name", "primary_type", "cmc", "mana_cost"})

#: Calls that take the printed card as an object: a zone move, an identity, a
#: split card's face, a shield keyed by the object.
IDENTITY_CALLS = frozenset({
    "_bin_spell_card", "put_card_into_hand", "put_card_into_library",
    "put_card_into_graveyard", "id", "whole_card", "is_face",
    "make_resolving_object_shield",
})

#: Every other raw read, by (module, function), and why it is the printed card
#: — never a text read.
PRINTED_CARD_READS: dict[tuple[str, str], str] = {
    ("engine/ai_scratch_copy.py", "_every_card"):
        "every card object in the game, collected for concealment (identity)",
    ("engine/counter_conditions.py", "spend_next_spell_promises"):
        "spent as the spell is cast (CR 601.2i), before any effect can change it",
    ("engine/damage_ledger.py", "record_cast"):
        "the cast record's object, written as the spell is cast (identity)",
    ("engine/handlers/_chosen.py", "_resolve_named_from"):
        "the triggering spell's name (CR 612.2)",
    ("engine/stack_targets.py", "stack_object_label"):
        "the name every seat sees a stack object by in a log line or a "
        "prompt (CR 612.2: a text change does not change a name)",
    ("engine/handlers/_record_conditions.py", "evaluate_record_condition"):
        "a cost record's object, not a stack object",
    ("engine/handlers/prevention.py", "chosen_shield_source"):
        "a source of damage chosen by its object (CR 609.7a, identity)",
    ("engine/handlers/prevention.py", "arm_mirror_damage"):
        "a source of damage chosen by its object (CR 609.7a, identity)",
    ("engine/handlers/prevention.py", "default_damage_source"):
        "a source of damage chosen by its object (CR 609.7a, identity)",
    ("engine/handlers/redirection.py", "redirect_damage_from_target_spell_until_eot"):
        "a redirection keyed by the spell's object (identity)",
    ("engine/handlers/repeats.py", "_claimable_exile_pile"):
        "an exile record's object, not a stack object",
    ("engine/handlers/stack.py", "_redirect_countered_card"):
        "the countered card moved to another zone (CR 701.6a, a zone move)",
    ("engine/legality_stack.py", "_enumerate_stack_ability_targets"):
        "an ability's source name for the picker",
    ("engine/mana_payment.py", "spell_mana_cost"):
        "the mana cost, which no text change reaches (CR 612.1)",
    ("engine/mixins/stack/cast_announcement.py", "arm_modal_mode_targets"):
        "the announcement (CR 601.2b-c), before any effect can change it",
    ("engine/mixins/stack/cast_completion.py", "_rebase_graveyard_targets"):
        "the announcement (CR 601.2c), before any effect can change it",
    ("engine/mixins/stack/choices/triggers.py", "_default_trigger_target"):
        "a triggered ability (CR 113.3c): not a spell, carries no text change",
    ("engine/mixins/stack/resolution.py", "counter_stack_object"):
        "the countered object as the event's subject (identity)",
    ("engine/mixins/stack/resolution.py", "_ability_execution_context"):
        "an ability's context card is its source's object (identity)",
    ("engine/mixins/stack/resolution.py", "_run_stack_item_resolution"):
        "the card that moves and names the resolution; its text is passed "
        "beside it (``text_card=``, ``text_change_effects=``)",
    ("engine/mixins/stack/trigger_targets.py", "_choose_trigger_mode"):
        "a triggered ability (CR 113.3c): not a spell, carries no text change",
    ("engine/mixins/stack/trigger_targets.py", "_trigger_target_candidates"):
        "a triggered ability (CR 113.3c): not a spell, carries no text change",
    ("engine/mixins/stack/trigger_targets.py", "_trigger_role_candidates"):
        "a triggered ability (CR 113.3c): not a spell, carries no text change",
    ("engine/mixins/target_announcements.py", "_stamp_stack_targets"):
        "stamped as the object is put on the stack, before any effect can change it",
    ("engine/mixins/target_announcements.py", "_stack_push"):
        "asked as the object is put on the stack, before any effect can change it",
    ("engine/mixins/target_announcements.py", "_announce_targeting_now"):
        "the announcing object as the event's subject (identity)",
    ("engine/mixins/target_announcements.py", "_announce_targeted_player"):
        "the announcing object as the event's subject (identity)",
    ("engine/targeting.py", "stack_object_mana_value"):
        "the mana value, which no text change reaches (CR 612.1)",
    ("engine/text_changes.py", "spell_text_card"):
        "the reader itself",
    ("engine/trigger_order.py", "trigger_card"):
        "a triggered ability (CR 113.3c): not a spell, carries no text change",
    ("web/serialization.py", "_serialize_stack_item"):
        "the wire sends the printed card with its ``text_changes``, as a "
        "permanent's is sent",
}

#: The functions that read what a resolving or waiting spell says — each must
#: ask ``spell_text_card``.
READS_THROUGH_SPELL_TEXT_CARD = frozenset({
    # CR 608.2b, re-asked by the changed text.
    ("engine/legality_resolution.py", "illegal_targets_refusal"),
    ("engine/legality_resolution.py", "resolving_targets_all_legal"),
    ("engine/legality_resolution.py", "_resolving_announcements"),
    ("engine/legality_resolution.py", "_announcement_target_legality"),
    ("engine/legality_resolution.py", "_player_target_legality"),
    ("engine/legality_resolution.py", "vanished_graveyard_target_refusal"),
    ("engine/legality_resolution.py", "sealed_graveyard_target_refusal"),
    ("engine/legality_resolution.py", "ability_target_verdicts"),
    ("engine/legality_resolution.py", "blank_illegal_resolution_targets"),
    ("engine/legality_resolution.py", "resettle_announced_target_seats"),
    # The resolution itself.
    ("engine/mixins/stack/resolution.py", "_seat_names_no_pile"),
    ("engine/mixins/stack/resolution.py", "_run_stack_item_resolution"),
    # Which targets a stack object chose, and how they may change (CR 115.7).
    ("engine/stack_targets.py", "announcements"),
    ("engine/stack_targets.py", "permanent_spell_targets_nothing"),
    ("engine/stack_targets.py", "_printed_target_instances"),
    ("engine/stack_targets.py", "_candidates"),
    ("engine/stack_targets.py", "change_slots"),
    ("engine/targeting.py", "spell_targets"),
    ("engine/targeting.py", "stack_object_target_spec"),
    ("engine/targeting.py", "single_spell_target"),
    ("engine/handlers/retargeting.py", "_legal_new_targets"),
    ("engine/legality_roles.py", "_role_target_legality"),
    ("engine/legality_roles.py", "_role_seat_target_legality"),
    # What a spell on the stack is, to another spell or a permanent.
    ("engine/legality_stack.py", "_enumerate_stack_targets"),
    ("engine/mixins/helpers.py", "_stack_item_colors"),
    ("engine/object_colors.py", "object_colors"),
    ("engine/object_creature_types.py", "object_creature_types"),
    ("engine/handlers/colors.py", "stack_target_still_described"),
    ("engine/handlers/stack.py", "counter_top_stack_spell"),
    ("engine/mixins/stack/choices/payments.py", "_redirect_unpaid_countered_card"),
    ("engine/counter_conditions.py", "_would_destroy_a_land_you_control"),
    ("engine/stack_statics.py", "stack_static_cost_sources"),
    ("engine/stack_statics.py", "stack_static_grant_sources"),
    # A text change asking what its spell target already says.
    ("engine/handlers/value_choices.py", "_first_creature_type_written_on_target"),
    # The AI and the wire.
    ("engine/ai_prompts.py", "_target_change_side"),
    ("web/prompt_cards.py", "_pick_destination"),
    ("web/serialization.py", "_stack_item_targets"),
})


def _modules():
    paths = sorted((ROOT / "engine").rglob("*.py")) + sorted((ROOT / "web").glob("*.py"))
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        # The shared cache's trees (`tests/source_index.py`): every other engine
        # sweep in the worker reads the same ones, where a parse of its own held
        # a second copy (~400 MB) in each of this file's four tests.
        yield rel, source_tree(path)


def _parents(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_function(node, parents) -> str:
    while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node = parents.get(node)
    return node.name if node is not None else "<module>"


def _is_stack_object(node, names) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    return isinstance(node, ast.Attribute) and node.attr in STACK_ATTRS


def _is_identity_use(read, parents) -> bool:
    parent = parents.get(read)
    if isinstance(parent, ast.Attribute) and parent.attr in IDENTITY_ATTRS:
        return True
    if isinstance(parent, ast.Compare):
        return True
    if isinstance(parent, ast.Call):
        func = parent.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name in IDENTITY_CALLS:
            return True
        if (
            name == "getattr" and len(parent.args) >= 2 and parent.args[0] is read
            and isinstance(parent.args[1], ast.Constant)
            and parent.args[1].value in IDENTITY_ATTRS
        ):
            return True
    return False


def stack_card_reads(modules):
    """``(module, function, line, identity)`` for every raw ``.card`` read of a
    stack object — ``X.card`` or ``getattr(X, "card", …)`` — in *modules*."""
    found = []
    for rel, tree in modules:
        names = STACK_NAMES | STACK_NAMES_BY_FILE.get(rel, frozenset())
        parents = _parents(tree)
        for node in ast.walk(tree):
            read = None
            if (
                isinstance(node, ast.Attribute) and node.attr == "card"
                and isinstance(node.ctx, ast.Load)
                and _is_stack_object(node.value, names)
            ):
                read = node
            elif (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) >= 2
                and _is_stack_object(node.args[0], names)
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "card"
            ):
                read = node
            if read is None:
                continue
            found.append((
                rel, _enclosing_function(read, parents), read.lineno,
                _is_identity_use(read, parents),
            ))
    return found


def functions_calling(modules, callee: str) -> set[tuple[str, str]]:
    """Every ``(module, function)`` in *modules* whose body calls *callee*."""
    found = set()
    for rel, tree in modules:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and (
                        (isinstance(sub.func, ast.Name) and sub.func.id == callee)
                        or (isinstance(sub.func, ast.Attribute) and sub.func.attr == callee)
                    )
                ):
                    found.add((rel, node.name))
                    break
    return found


def census_failures(modules) -> list[str]:
    """Everything the census finds wrong in *modules* — empty on a tree where
    every text read of a spell asks ``spell_text_card``."""
    modules = list(modules)
    failures = []
    reads = stack_card_reads(modules)
    for rel, function, line, identity in reads:
        if identity or (rel, function) in PRINTED_CARD_READS:
            continue
        failures.append(
            f"{rel}:{line} ({function}) reads a stack object's printed card for "
            "something other than its identity: ask spell_text_card(item), or "
            "list it in PRINTED_CARD_READS with why the printed card is right"
        )
    calling = functions_calling(modules, "spell_text_card")
    for rel, function in sorted(READS_THROUGH_SPELL_TEXT_CARD - calling):
        failures.append(f"{rel} ({function}) reads a spell's text without spell_text_card")
    return failures


def test_every_stack_card_read_is_an_identity_or_goes_through_the_reader():
    modules = list(_modules())
    reads = stack_card_reads(modules)
    # A floor on what was examined: a scan that matched nothing would pass.
    assert len(reads) >= 60, len(reads)
    assert census_failures(modules) == []


def test_the_text_readers_are_many_and_each_asks_spell_text_card():
    calling = functions_calling(list(_modules()), "spell_text_card")
    assert len(READS_THROUGH_SPELL_TEXT_CARD) >= 35
    assert READS_THROUGH_SPELL_TEXT_CARD <= calling, sorted(
        READS_THROUGH_SPELL_TEXT_CARD - calling
    )


def test_no_printed_card_read_entry_is_dead():
    """An entry whose read has gone (moved to the reader, or the function
    renamed) is removed, so the table cannot excuse a later read by accident."""
    live = {(rel, function) for rel, function, _line, identity in stack_card_reads(_modules()) if not identity}
    assert set(PRINTED_CARD_READS) <= live, sorted(set(PRINTED_CARD_READS) - live)


def test_the_resolution_folds_the_record_and_carries_it():
    """``_resolve_card`` receives the printed card and the record; it folds
    them once (``spell_text_of``) for every text read, its permanent arm
    (``_resolve_permanent_spell``) carries them onto the permanent a
    permanent spell becomes (CR 400.7a), and ``_apply_spell_text`` compiles
    what the spell says (``text_card``)."""
    modules = list(_modules())
    assert ("engine/mixins/stack/resolution.py", "_resolve_card") in functions_calling(
        modules, "spell_text_of",
    )
    assert (
        "engine/mixins/stack/permanent_spell_resolution.py", "_resolve_permanent_spell",
    ) in functions_calling(modules, "carry_spell_text_changes")
    tree = dict(modules)["engine/mixins/oracle_instructions.py"]
    (apply_spell_text,) = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_spell_text"
    ]
    assert "text_card" in [arg.arg for arg in apply_spell_text.args.kwonlyargs + apply_spell_text.args.args]
    selected = [
        sub for sub in ast.walk(apply_spell_text)
        if isinstance(sub, ast.Call) and getattr(sub.func, "attr", None) == "_select_executable_instruction"
    ]
    assert selected and all(
        isinstance(call.args[0], ast.Name) and call.args[0].id == "program_card"
        for call in selected
    )

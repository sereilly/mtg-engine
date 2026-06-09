"""One-shot script to extract mixin classes from game.py.

Run from the project root: python scripts/extract_mixins.py
"""
from __future__ import annotations

import ast
import os
import textwrap

GAME_PY = os.path.join(os.path.dirname(__file__), "..", "engine", "game.py")
MIXINS_DIR = os.path.join(os.path.dirname(__file__), "..", "engine", "mixins")

# Map: method name -> mixin key
METHOD_TO_MIXIN: dict[str, str] = {
    # helpers
    "_find_controlled_permanent": "helpers",
    "_is_summoning_sick": "helpers",
    "_public_phase_name": "helpers",
    "_receives_priority": "helpers",
    "_make_expiry_tag": "helpers",
    "_expire_tagged_effects": "helpers",
    "_on_step_or_phase_begin": "helpers",
    "_on_step_or_phase_end": "helpers",
    "_normalize_mana_color": "helpers",
    "clear_mana_pools": "helpers",
    "_permanent_to_graveyard": "helpers",
    # phase_steps
    "_resolve_priority_window": "phase_steps",
    "start_priority_window": "phase_steps",
    "clear_priority_window": "phase_steps",
    "has_priority": "phase_steps",
    "note_priority_action_taken": "phase_steps",
    "_next_player_index": "phase_steps",
    "pass_priority": "phase_steps",
    "add_extra_turn": "phase_steps",
    "add_extra_phase": "phase_steps",
    "add_extra_step": "phase_steps",
    "add_additional_step_after_phase": "phase_steps",
    "skip_next_turn": "phase_steps",
    "skip_next_phase": "phase_steps",
    "skip_next_step": "phase_steps",
    "_consume_skip": "phase_steps",
    "_phase_steps": "phase_steps",
    "_next_phase_after": "phase_steps",
    "next_unskipped_phase_after": "phase_steps",
    "_compute_next_active_player": "phase_steps",
    "_enter_main_phase": "phase_steps",
    "_close_current_priority_step": "phase_steps",
    "_enter_combat_step": "phase_steps",
    # turn_management
    "select_starting_player": "turn_management",
    "deal_opening_hands": "turn_management",
    "take_mulligan": "turn_management",
    "keep_hand": "turn_management",
    "pregame_mulligan_draw": "turn_management",
    "start_turn": "turn_management",
    "start_next_turn": "turn_management",
    "resolve_draw_step": "turn_management",
    "get_untap_land_selection_options": "turn_management",
    "resolve_untap_step": "turn_management",
    "use_channel_mana": "turn_management",
    "tap_land_for_mana": "turn_management",
    # stack_casting
    "cast_from_hand": "stack_casting",
    "activate_permanent_ability": "stack_casting",
    "confirm_search_library": "stack_casting",
    "confirm_reorder_library": "stack_casting",
    "queue_permanent_ability": "stack_casting",
    "tap_permanent": "stack_casting",
    "queue_from_hand": "stack_casting",
    "_validate_cast_targets": "stack_casting",
    "_infer_x_value": "stack_casting",
    "_parse_mana_cost": "stack_casting",
    "_pay_mana_cost": "stack_casting",
    "resolve_stack": "stack_casting",
    "resolve_top_of_stack": "stack_casting",
    "_resolve_card": "stack_casting",
    "_select_executable_instruction": "stack_casting",
    # oracle_instructions
    "_execute_oracle_instruction": "oracle_instructions",
    "_apply_spell_text": "oracle_instructions",
    "_apply_cast_triggers": "oracle_instructions",
    "_apply_spell_resolved_triggers": "oracle_instructions",
    "_apply_global_buff": "oracle_instructions",
    "_apply_aura_effect": "oracle_instructions",
    # effects
    "_trigger_aura_death_effects": "effects",
    "_destroy_target_permanent": "effects",
    "_tap_or_untap_target": "effects",
    "_grant_regeneration_shield": "effects",
    "_prevent_damage": "effects",
    "_add_mana_from_text": "effects",
    "_return_creature_from_graveyard": "effects",
    "_reanimate_creature_to_battlefield": "effects",
    "_bounce_target_creature": "effects",
    "_sacrifice_creature_for_mana": "effects",
    "_apply_color_override": "effects",
    "_process_land_enters": "effects",
    "_process_land_dies": "effects",
    "_fastbond_count": "effects",
    # upkeep
    "get_upkeep_pay_triggers": "upkeep",
    "resolve_upkeep": "upkeep",
    # ending_phase
    "resolve_end_step": "ending_phase",
    "close_end_step": "ending_phase",
    "resolve_cleanup_step": "ending_phase",
    # permanent_state
    "_initialize_permanent_state": "permanent_state",
    "_refresh_dynamic_creatures": "permanent_state",
    "_has_keyword": "permanent_state",
    "_recalculate_lord_buffs": "permanent_state",
    # combat
    "_has_any_legal_attacker": "combat",
    "_has_any_legal_block": "combat",
    "advance_combat_phase": "combat",
    "_reset_combat_state": "combat",
    "_prune_combat_state": "combat",
    "_can_block_attacker": "combat",
    "_destroy_marked_creatures": "combat",
    "declare_attackers": "combat",
    "declare_blockers": "combat",
    "_combat_blockers_for_attacker": "combat",
    "_needs_manual_damage_assignment": "combat",
    "_build_auto_damage_assignment": "combat",
    "resolve_combat_damage": "combat",
    "get_combat_state": "combat",
    "can_attack": "combat",
    "_must_attack_if_able": "combat",
    "end_combat": "combat",
    # game_ending
    "concede": "game_ending",
    "get_winner": "game_ending",
    "is_game_over": "game_ending",
    "check_state_based_actions": "game_ending",
}

MIXIN_CLASS_NAMES: dict[str, str] = {
    "helpers": "GameHelpersMixin",
    "phase_steps": "PhaseStepsMixin",
    "turn_management": "TurnManagementMixin",
    "stack_casting": "StackCastingMixin",
    "oracle_instructions": "OracleInstructionsMixin",
    "effects": "EffectsMixin",
    "upkeep": "UpkeepMixin",
    "ending_phase": "EndingPhaseMixin",
    "permanent_state": "PermanentStateMixin",
    "combat": "CombatMixin",
    "game_ending": "GameEndingMixin",
}

MIXIN_IMPORTS: dict[str, str] = {
    "helpers": """\
from __future__ import annotations

from ..models import CardDefinition, Permanent, PlayerState
from ._constants import _NO_PRIORITY_STEPS
""",
    "phase_steps": """\
from __future__ import annotations

from ._constants import _TURN_PHASES, _PHASE_STEPS, _NO_PRIORITY_STEPS
""",
    "turn_management": """\
from __future__ import annotations

import random

from ..models import CardDefinition, PlayerState
""",
    "stack_casting": """\
from __future__ import annotations

import random
import re

from ..classifier import CardClassification, classify_card
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import OracleInstruction, compile_card_oracle, lex_oracle_text
from ._constants import _MANA_SYMBOLS
""",
    "oracle_instructions": """\
from __future__ import annotations

import re

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import OracleInstruction, _COLOR_WORD_TO_SYMBOL, compile_card_oracle
from ._constants import _COLOR_ROD_TRIGGERS, _EOT_METADATA_KEYS, _MANA_SYMBOLS
""",
    "effects": """\
from __future__ import annotations

import re

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import lex_oracle_text
""",
    "upkeep": """\
from __future__ import annotations

from ..models import PlayerState
from ..oracle import OracleInstruction, compile_card_oracle
from ._constants import _UPKEEP_PAY_KINDS
""",
    "ending_phase": """\
from __future__ import annotations

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle
from ._constants import _EOT_METADATA_KEYS
""",
    "permanent_state": """\
from __future__ import annotations

import re

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle
""",
    "combat": """\
from __future__ import annotations

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle
""",
    "game_ending": """\
from __future__ import annotations

from ..models import CardDefinition, Permanent, PlayerState
""",
}

# Ordered for Game inheritance (most specific first, most foundational last)
MIXIN_ORDER = [
    "game_ending",
    "combat",
    "ending_phase",
    "upkeep",
    "turn_management",
    "phase_steps",
    "stack_casting",
    "oracle_instructions",
    "permanent_state",
    "effects",
    "helpers",
]


def get_source_lines(source: str) -> list[str]:
    return source.splitlines(keepends=True)


def extract_method_source(source_lines: list[str], node: ast.FunctionDef) -> str:
    """Extract the source text for a method, preserving original indentation."""
    start = node.lineno - 1  # 0-indexed
    end = node.end_lineno      # inclusive end, 0-indexed exclusive
    return "".join(source_lines[start:end])


def dedent_method(source: str) -> str:
    """Remove one level of class-level indentation (4 spaces) from a method."""
    lines = source.splitlines(keepends=True)
    result = []
    for line in lines:
        if line.startswith("    "):
            result.append(line[4:])
        else:
            result.append(line)
    return "".join(result)


def main() -> None:
    with open(GAME_PY, "r", encoding="utf-8") as f:
        source = f.read()
    source_lines = get_source_lines(source)

    tree = ast.parse(source)

    # Find the Game class
    game_class: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Game":
            game_class = node
            break

    assert game_class is not None, "Could not find Game class"

    # Collect methods and their source, grouped by mixin
    mixin_methods: dict[str, list[tuple[str, str]]] = {k: [] for k in MIXIN_CLASS_NAMES}
    methods_to_remove: list[tuple[int, int]] = []  # (start_line, end_line) 1-indexed

    for item in game_class.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = item.name
        if name == "__post_init__":
            continue  # stays in Game
        mixin_key = METHOD_TO_MIXIN.get(name)
        if mixin_key is None:
            print(f"WARNING: {name} not assigned to any mixin, stays in Game")
            continue
        method_source = extract_method_source(source_lines, item)
        method_source_dedented = dedent_method(method_source)
        mixin_methods[mixin_key].append((name, method_source_dedented))
        methods_to_remove.append((item.lineno, item.end_lineno))

    # Write mixin files
    os.makedirs(MIXINS_DIR, exist_ok=True)
    for mixin_key in MIXIN_ORDER:
        class_name = MIXIN_CLASS_NAMES[mixin_key]
        methods = mixin_methods[mixin_key]
        imports = MIXIN_IMPORTS[mixin_key]

        lines_out: list[str] = [imports, "\n"]
        lines_out.append(f"class {class_name}:\n")

        if not methods:
            lines_out.append("    pass\n")
        else:
            for i, (method_name, method_src) in enumerate(methods):
                # Indent to class level
                indented = textwrap.indent(method_src, "    ")
                lines_out.append(indented)
                if i < len(methods) - 1:
                    lines_out.append("\n")

        mixin_file = os.path.join(MIXINS_DIR, f"{mixin_key}.py")
        with open(mixin_file, "w", encoding="utf-8") as f:
            f.write("".join(lines_out))
        print(f"Written: {mixin_file} ({len(methods)} methods)")

    # Update game.py: remove extracted methods and add mixin inheritance
    # Sort removal ranges by start line descending so we can safely splice
    methods_to_remove.sort(key=lambda x: x[0], reverse=True)

    new_lines = list(source_lines)
    for start_line, end_line in methods_to_remove:
        start_idx = start_line - 1  # 0-indexed
        end_idx = end_line          # exclusive end
        # Remove the method lines plus any preceding blank lines inside class
        while start_idx > 0 and new_lines[start_idx - 1].strip() == "":
            start_idx -= 1
        del new_lines[start_idx:end_idx]

    new_source = "".join(new_lines)

    # Add mixin imports near the top of game.py (after existing imports)
    mixin_class_list = ", ".join(MIXIN_CLASS_NAMES[k] for k in MIXIN_ORDER)
    mixin_import_names = "\n    ".join(MIXIN_CLASS_NAMES[k] + "," for k in MIXIN_ORDER)
    mixin_import_block = f"from .mixins import (\n    {mixin_import_names}\n)\n"

    # Insert after the last existing import line
    import_insert_marker = "from .mixins._constants import ("
    insert_pos = new_source.find(import_insert_marker)
    # Find end of that import block
    block_end = new_source.find("\n)\n", insert_pos)
    insert_after = block_end + 3  # after the closing paren + newline

    new_source = new_source[:insert_after] + mixin_import_block + new_source[insert_after:]

    # Update Game class definition to inherit from mixins
    # Find "@dataclass\nclass Game:"
    class_def_old = "@dataclass\nclass Game:"
    mixin_inheritance = "(\n    " + ",\n    ".join(MIXIN_CLASS_NAMES[k] for k in MIXIN_ORDER) + ",\n)"
    class_def_new = f"@dataclass\nclass Game{mixin_inheritance}:"
    new_source = new_source.replace(class_def_old, class_def_new)

    with open(GAME_PY, "w", encoding="utf-8") as f:
        f.write(new_source)
    print(f"\nUpdated game.py")

    # Update engine/mixins/__init__.py
    init_lines = ["# Mixin classes for the Game dataclass\n"]
    for key in MIXIN_ORDER:
        class_name = MIXIN_CLASS_NAMES[key]
        init_lines.append(f"from .{key} import {class_name}\n")
    init_path = os.path.join(MIXINS_DIR, "__init__.py")
    with open(init_path, "w", encoding="utf-8") as f:
        f.write("".join(init_lines))
    print(f"Updated: {init_path}")


if __name__ == "__main__":
    main()

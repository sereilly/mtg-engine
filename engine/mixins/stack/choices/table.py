"""The prompt table: every kind of pending choice, registered in one order.

A kind's row is a ``ChoiceSpec`` — what answers it, what a non-interactive
seat does instead, and how the web layer renders, gates and refuses around it
(``engine/pending_choices.py`` says what each field means). A row names its
resolver and default through the game (``game._resolve_…``), and it is defined
beside them, as ``<KIND>_SPEC`` at the foot of the module of the family that
answers it: a family of this package, or ``engine/mixins/entry_choices.py`` for
what an entering permanent chooses. A row whose answer is not a family's method
sits in the family whose subject it is — madness's offer to cast
(``engine/madness.py``) in ``spells``, the CR 700.3 piles (``engine/piles.py``)
in ``pile_picks``, an opponent's choice of what the damage hits
(``engine/mixins/effects.py``) in ``permanents``.

**Row order is behaviour.** ``Game.iter_pending_prompts`` yields owed prompts
in registration order, and the AI's drain, ``waiting_prompt`` and
``blocking_prompt`` each act on the first one it yields. That is why the rows
are registered here, in one list, rather than by their families: registered
where they are defined, the order would be whichever module happened to import
first. A family module only defines its rows, and this list is the one index of
every prompt in the engine. A new kind is its row at the foot of its family's
module and its name appended at the bottom of this list.
"""

from __future__ import annotations

from ....pending_choices import register_choices
# ``engine/mixins/entry_choices.py`` — the entering permanent's prompts — not
# ``engine/entry_choices.py``, the table of what one may choose.
from ... import entry_choices
from . import (
    card_names,
    hand,
    library,
    numbers,
    optional_pay,
    payments,
    permanents,
    pile_picks,
    replacements,
    sacrifice,
    search,
    spells,
    triggers,
    values,
)


register_choices(
    replacements.EFFECT_ORDER_SPEC,
    hand.HAND_TO_LIBRARY_SPEC,
    search.SEARCH_LIBRARY_SPEC,
    search.SEARCH_DESTINATION_SPEC,
    library.LOOK_TOP_PICK_SPEC,
    permanents.TAP_ANY_NUMBER_SPEC,
    permanents.UNTAP_UP_TO_SPEC,
    search.SEARCH_EXILE_CARDS_SPEC,
    library.REORDER_LIBRARY_SPEC,
    library.SCRY_SPEC,
    hand.REVEALED_HAND_PICK_SPEC,
    pile_picks.OPPONENT_PICKS_REVEALED_SPEC,
    hand.DISCARD_SPEC,
    sacrifice.BALANCE_SPEC,
    sacrifice.SACRIFICE_SPEC,
    values.MANA_COLOR_CHOICE_SPEC,
    values.COLOR_SET_CHOICE_SPEC,
    library.REVEALED_DRAW_BUYOUT_SPEC,
    optional_pay.PAY_LIFE_TO_SAVE_SPEC,
    optional_pay.OPTIONAL_PAY_SPEC,
    triggers.TRIGGER_TARGET_SPEC,
    triggers.ORDER_TRIGGERS_SPEC,
    optional_pay.REFLEXIVE_TARGET_SPEC,
    spells.COPY_SPELL_TARGET_SPEC,
    optional_pay.DISCARD_UNLESS_PAY_LIFE_SPEC,
    hand.HAND_REVEAL_SPEC,
    permanents.FACE_DOWN_LOOK_SPEC,
    numbers.DRAW_UP_TO_SPEC,
    numbers.PAY_ANY_AMOUNT_SPEC,
    numbers.NUMBER_CHOICE_SPEC,
    numbers.SECRET_NUMBER_SPEC,
    numbers.BID_LIFE_SPEC,
    values.LAND_TYPE_CHOICE_SPEC,
    values.LAND_TYPE_SWAP_SPEC,
    values.CARD_TYPE_CHOICE_SPEC,
    values.CREATURE_TYPE_CHOICE_SPEC,
    values.COLOR_CHOICE_SPEC,
    payments.MANA_PAYMENT_SPEC,
    permanents.PLAYER_CHOICE_SPEC,
    permanents.CAST_CHOICE_SPEC,
    spells.MADNESS_CAST_SPEC,
    spells.RETARGET_CHOICE_SPEC,
    permanents.PERMANENT_CHOICE_SPEC,
    permanents.PERMANENT_SET_CHOICE_SPEC,
    numbers.FLIP_AGAIN_SPEC,
    numbers.REPEAT_PROCESS_SPEC,
    hand.EXILE_FROM_HAND_CHOICE_SPEC,
    hand.EXILE_HAND_PILE_CHOICE_SPEC,
    pile_picks.LIBRARY_PILE_SPLIT_SPEC,
    pile_picks.PILE_EXILE_CHOICE_SPEC,
    pile_picks.PILE_SEARCH_SPEC,
    pile_picks.PILE_SPLIT_SPEC,
    pile_picks.PILE_CHOICE_SPEC,
    library.LIBRARY_CYCLE_OFFER_SPEC,
    pile_picks.LINKED_EXILE_RETURN_SPEC,
    hand.PUT_FROM_HAND_CHOICE_SPEC,
    values.TEXT_CHANGE_VOCABULARY_SPEC,
    sacrifice.AGGREGATE_SACRIFICE_SPEC,
    library.LIBRARY_END_CHOICE_SPEC,
    pile_picks.GRAVEYARD_PILE_CHOICE_SPEC,
    pile_picks.GRAVEYARD_EXILE_PICK_SPEC,
    hand.CHOOSE_CARDS_IN_HAND_SPEC,
    spells.FACE_DOWN_CAST_SPEC,
    spells.WORD_OF_COMMAND_SPEC,
    permanents.OPPONENT_DAMAGE_SPEC,
    card_names.NAME_AND_STRIP_SPEC,
    card_names.CHOOSE_CARD_NAME_SPEC,
    card_names.NAME_THEN_REVEAL_TOP_SPEC,
    pile_picks.EXILED_PILE_CLAIM_SPEC,
    pile_picks.GRAVEYARD_PICK_FOR_PRICE_SPEC,
    card_names.NAME_THEN_CONSULT_SPEC,
    card_names.NAME_AND_RANDOM_REVEAL_SPEC,
    values.ENTER_CHOICE_SPEC,
    entry_choices.ENTRY_EXILE_SPEC,
    entry_choices.BODY_CHOICE_SPEC,
    spells.MODAL_MODE_TARGETS_SPEC,
    spells.OPPONENT_MODE_CHOICE_SPEC,
    triggers.MODE_CHOICE_SPEC,
    permanents.LOYALTY_RECIPIENT_SPEC,
    # The CR 614 offers: a replacement suspended on a decision keeps its own
    # queue (``engine/replacement_choices.py``) but is a prompt like any other.
    replacements.COMMANDER_ZONE_CHANGE_SPEC,
    replacements.LENG_DISCARD_SPEC,
    replacements.OPTIONAL_DAMAGE_REDIRECT_SPEC,
    replacements.ENTRY_DISCARD_TOLL_SPEC,
    replacements.DRAW_BECOMES_COUNTER_SPEC,
    replacements.REVEAL_UNTIL_KIND_DRAW_SPEC,
    replacements.SKIP_DRAW_SPEC,
    replacements.LAMP_DRAW_SPEC,
    replacements.OUTSIDE_GAME_DRAW_SPEC,
    replacements.RETURN_FROM_GRAVEYARD_INSTEAD_OF_DRAW_SPEC,
    sacrifice.KEEP_PERMANENTS_SPEC,
    hand.OUTSIDE_GAME_PICK_SPEC,
    entry_choices.ENTRY_REVEAL_SPEC,
    spells.TARGET_GROUP_ORDER_SPEC,
    # Append a new kind here, at the bottom.
)

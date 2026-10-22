"""What compiled instructions target: the walk every derivation ends in.

:func:`_from_instructions` answers "what does this sequence choose?" with the
first instruction that describes a choice, walking into the wrappers a
targeting step can sit inside (:data:`_WRAPPER_STEP_KEYS`), and
:func:`_first_described_slot` hands the instruction back beside the spec, for
CR 601.2c's "must a target be named?", which only that slot's printed
quantifier answers. One instruction is read by :func:`_from_instruction`
against the evidence in order: a shared roles announcement, the payload
readers (``engine/payload_target_specs.py``), the lowering's ``targets``
description (``engine/target_descriptions.py``), a ``type_filter`` for the
kinds :data:`_TYPE_FILTER_NAMES_THE_TARGET` lists, and last the kind itself
(:data:`_KIND_TO_SPEC`). A condition may be the only place a spell says
"target" (:func:`_condition_target_spec`).

What an instruction targets does not depend on whether a spell, an ability or
a trigger produced it, so ``targeting.derive_cast_spec``,
``derive_activation_spec`` and ``derive_instruction_spec`` all end here. Split
out of ``engine/targeting.py`` at the 2,000-line cap; a caller imports a name
from here.
"""

from __future__ import annotations

from .divided_damage import CARD_DIVIDED, CHOSEN
from .target_roles import payload_own_role
from .target_descriptions import (_from_targets_payload, _kind_for_type_filter,
                                  _narrowing_flags)
from .payload_target_specs import _KIND_TO_SPEC_FROM_PAYLOAD


#: The instruction kinds whose ``type_filter`` describes **the object the
#: caster picks**, rather than the class the effect sweeps.
#:
#: The third kind-keyed evidence table in this module, beside
#: :data:`_KIND_TO_SPEC_FROM_PAYLOAD` and :data:`_KIND_TO_SPEC`, and it exists
#: because ``type_filter`` is the one payload key that means two different
#: things. "Destroy target permanent" and "destroy all black creatures" both
#: carry ``{"type_filter": "creature"}``: on the first it is the target
#: description (CR 115.1a's "target [something]"), on the second it is the
#: class the sweep affects, and the payload alone cannot tell them apart.
#:
#: :func:`_from_instruction` used to read the key on *any* kind, which is this
#: module's one guess — the thing its docstring says it does not do. Six mass
#: spells (Cleanse, Jokulhaups, Tivadar's Crusade, Riptide, Battle Cry, Reset)
#: and five more whose sweep sits on a trigger reported a target they never
#: choose, and the client refused to cast four of them at all: its picker
#: aborts a cast when the candidate list comes back empty, so "Destroy all
#: black creatures" was uncastable on a board with no creatures. Wrath of God
#: was the accidental control — "destroy all creatures" has a kind of its own
#: (``destroy_all_creatures``) with the class baked into the *name* and so no
#: filter for the reader to misread.
#:
#: One entry today, and that is the measurement rather than an oversight: every
#: other targeted line in the pool carries the lowering's own ``targets``
#: description, which is deliberate evidence and is read first. A kind that
#: needs to be here and is not answers None, and the ratchet in
#: `tests/engine/test_targeting.py` fails on the card that targets and derives
#: no prompt — the loud direction. A sweep needs no entry at all, so the defect
#: cannot come back by omission.
_TYPE_FILTER_NAMES_THE_TARGET = frozenset({
    # "Destroy target permanent", narrowed by a printed noun the lowering
    # carries as payload rather than as a `targets` description
    # (`lowering/destruction.py`). Hooded Blightfang's "destroy that
    # planeswalker" is the pool's only one; the same kind's ordinary printed
    # forms describe their target and never reach here.
    "destroy_target_permanent",
})


def _spec_from_type_filter(payload: dict) -> dict | None:
    """The picker *payload*'s ``type_filter`` describes, or None for none.

    Only reached for a kind :data:`_TYPE_FILTER_NAMES_THE_TARGET` lists. A
    filter no picker matches answers None rather than short-circuiting the
    whole derivation, so the kind's own :data:`_KIND_TO_SPEC` row still gets
    its say.
    """
    type_filter = payload.get("type_filter")
    if not type_filter:
        return None
    kind = _kind_for_type_filter(type_filter)
    if kind is None:
        return None
    return {"kind": kind, **_narrowing_flags(payload)}


# Instruction kinds whose whole spec is fixed by the kind itself. A lace always
# targets a spell or permanent; a graveyard-return always targets a card in a
# graveyard. `legality.py` used to read that off the card's *text*; the compiled
# program already carries it in the kind.
#
# The flags beside a kind describe the same thing the kind's *handler* does, so
# they are read off the handler rather than off the card. `reanimate_creature`
# is the worked example and also the caveat: its handler reads the caster's own
# graveyard *unless* the payload says `any_graveyard`, in which case it reads
# the graveyard of the seat the caster named. So `own_graveyard_only` belongs to
# the kind **and its payload** — never to whether the words "your graveyard"
# happen to appear, which would be the text cascade this module replaced.
#
# One table, consulted by the cast side and the activation side alike: what an
# instruction targets is a property of the instruction, not of whether a spell
# or an ability produced it. `grant_target_flying_until_eot` is Jump when a
# spell carries it and Flying Carpet's ability when a permanent does, and both
# want the same creature picker.
_KIND_TO_SPEC: dict[str, dict] = {
    "recolor_target_from_text": {"kind": "spell_or_permanent"},
    # Unsubstantiate: a spell on the stack or a creature on the battlefield —
    # the recolor picker's zones, narrowed to creatures on the permanent half.
    "return_spell_or_creature_to_hand": {
        "kind": "spell_or_permanent", "permanent_kind": "creature",
    },
    "mark_text_modified": {"kind": "permanent"},
    "counter_top_stack_spell": {"kind": "stack"},
    # "Target spell's controller exiles it …" (Ertai's Meddling). The same
    # picker and for the same reason: what the announcement chooses is an object
    # on the stack (CR 115.1). The seat in the printed possessive is read off
    # that object at resolution and is not a second target — "target" modifies
    # *spell*, so a row naming a player would put a seat picker in front of a
    # spell the caster never gets to choose.
    "exile_target_spell": {"kind": "stack"},
    "berserk_pump": {"kind": "creature"},
    # "Target creature **defending player controls** can block any number of
    # creatures this turn." (Blaze of Glory.) The seat was missing from this
    # row and enforced nowhere else, so the spell granted the permission to the
    # *caster's* own creature — a printed restriction that reached the picker,
    # the cast gate and the handler as nothing at all. It is a spec key rather
    # than a branch because `legality_enumeration._enumerate_targets` already answers the
    # flag, and answers it for a spell now: the seat is the live combat's.
    "grant_unlimited_blocking": {"kind": "creature", "defending_player_only": True},
    "target_gains_life": {"kind": "any"},
    # "Remove target creature **defending player controls** from combat."
    # (False Orders.) Blaze of Glory's row and Blaze of Glory's defect: the
    # seat was missing here and enforced nowhere else, so the spell could be
    # aimed at an *attacking* creature — the handler then marked it, unblocked
    # nothing and left it attacking, and the log said it had been removed.
    # No seat ever did that until a simulated seat had priority in the
    # declare-blockers step (round 4); then two of two LEA casts did.
    "remove_creature_from_combat": {"kind": "creature", "defending_player_only": True},
    "grant_target_flying_until_eot": {"kind": "creature"},
    "simulacrum_redirect": {"kind": "creature"},
    "exile_creature_gain_life_equal_to_power": {"kind": "creature"},
    "bounce_target_creature": {"kind": "creature"},
    "phase_out_target_creature_until_source_leaves": {"kind": "creature"},
    "exchange_ante_with_top_library": {"kind": "none"},
    # Dream Coat: "Enchanted creature becomes the color or colors of your
    # choice." The *permanent* is not chosen — an Aura's ability acts on its
    # own host (CR 303.4) — so there is no target picker; what the activator
    # chooses is a colour, which rides `mana_color` like every other CR 608.2d
    # choice. A positive "nothing to point at", not an absent derivation:
    # without the row the ability answered None and the guard could not tell
    # the two apart.
    "recolor_enchanted_chosen_color": {"kind": "none"},
    # Shyft: the same positive "nothing to point at" — the sentence names
    # the source itself, so no picker is offered and none is missing.
    "recolor_self_chosen_color": {"kind": "none"},
    # "{1}: This creature becomes **the color of your choice** until end of
    # turn." (Rainbow Crow, Kavu Chameleon.) The same answer for the turn-long
    # spelling: the colour is chosen while the effect is applied (CR 608.2d,
    # the ``choose_color`` step in front of this one) and the permanent is the
    # ability's own source. Without the row the ability answered None, which
    # the activation guard reads as "the derivation lost its evidence" — it
    # named both cards at Invasion's early promotion rehearsal, on the phrase
    # "of your choice".
    "recolor_self_until_eot": {"kind": "none"},
    # "This creature gains protection from **the color of your choice** until
    # end of turn." (Knight of Dawn.) The third of the same positive answer,
    # and the one that shows what the row is actually *for*: "of your choice"
    # is the phrase a target probe watches for, and here it names a
    # **characteristic** rather than an object. CR 608.2d makes a colour part
    # of the resolution and the word rides `mana_color` like every other one;
    # the permanent it applies to is the ability's own source, which nobody
    # chooses. So there is nothing to point at, and saying so positively is
    # what lets a guard tell "this ability targets nothing" from "the
    # derivation lost its evidence".
    #
    # The row is the *kind's*, not the card's — every "this creature gains
    # <keyword> until end of turn" in the pool names its own source, whether
    # the keyword is printed (Fetid Imp's deathtouch) or chosen.
    "grant_self_keyword_until_eot": {"kind": "none"},
    "tap_or_untap_target": {"kind": "permanent"},
    # "Target creature becomes an enchantment and loses all abilities …"
    # (Soul Sculptor.) The picker offers a permanent; which one is narrowed by
    # the `targets` description the lowering emits, exactly as the ability
    # removal beside it in the same sentence is.
    "set_card_types_target": {"kind": "permanent"},
    "tap_target_player_lands_and_drain_mana": {"kind": "player"},
    # Phyrexian Furnace: "{T}: Exile the bottom card of **target player's**
    # graveyard." The pile is chosen (CR 115.1) and the card in it is not —
    # CR 404.1/404.2 order the zone, so "the bottom card" has exactly one answer
    # once the seat is known. So the picker asks for a player and nothing
    # else; a card picker here would offer a choice the sentence does not
    # make.
    "exile_graveyard_position": {"kind": "player"},
    "reorder_target_library_top": {"kind": "player"},
    # "…can be the target of spells and abilities controlled by **target
    # player** as though it didn't have shroud" (Autumn Willow). The ability
    # targets a *player* while the creature carrying it cannot be targeted at
    # all, which is legal and is the whole card: CR 702.18 stops spells and
    # abilities from choosing the permanent, and says nothing about what the
    # permanent's own abilities may choose.
    "waive_shroud_for_target_player": {"kind": "player"},
    "return_all_owned_artifacts_to_hand": {"kind": "player"},
    # Word of Command looks at *target opponent's* hand: the caster's own seat is
    # not a legal choice (CR 102.2/102.3).
    "peek_hand_and_force_play": {"kind": "player", "opponents_only": True},
    # Fork copies the chosen spell and lets the caster choose new targets for the
    # copy, so the UI runs a second prompt rather than sending the cast at once.
    "copy_top_stack_spell": {
        "kind": "stack",
        "copies_spell": True,
        "stack_instant_sorcery_only": True,
    },
    # "The next time a source of your choice would deal damage to you this turn":
    # the source may be a permanent on any battlefield or a spell on the stack,
    # which `also_stack` folds into one prompt. The engine matches the chosen
    # source by identity, so no colour filter narrows it.
    "grant_reverse_damage_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Bone Mask prints the same seven words and so runs the same prompt; what
    # its shield does after absorbing is the interceptor's business, not the
    # picker's.
    "grant_exile_prevention_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Shadowbane prints the same seven words again; what its shield then covers
    # is the interceptor's business, not the picker's.
    "grant_team_prevention_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Samite Ministration and Protective Sphere print the phrase behind a
    # blanket — "Prevent all damage … this turn by a source of your choice" —
    # and so run the same prompt. How long the shield then lasts is the
    # interceptor's business, not the picker's.
    "grant_chosen_source_blanket_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    "arm_mirror_damage": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Dark Sphere prints the same phrase and so runs the same prompt — a
    # permanent on any battlefield or a spell on the stack. What its shield then
    # does with the chosen source is the handler's business, not the picker's.
    "grant_half_prevention_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Nova Pentacle: "The next time **a source of your choice** would deal damage
    # to you this turn…". The same prompt those two run — a permanent on any
    # battlefield or a spell on the stack — because it is the same printed
    # phrase. The creature that takes the redirected damage is *not* here: an
    # opponent picks it (CR 601.2c's chooser is not always the controller), so
    # it is a prompt the resolution arms rather than one this picker runs.
    # Reflect Damage prints the same seven words a third time — the source may
    # be a permanent on any battlefield or a spell on the stack. It names no
    # recipient at all, which changes what the *record* watches and nothing
    # about what the caster is asked for.
    # Nova Pentacle and Reflect Damage keep that flat spec through
    # `_chosen_source_redirect_spec`, which reads the payload: General's Regalia
    # prints the same first half and then announces a **target creature you
    # control** to take the damage, so the kind can no longer settle its own
    # picker. See that function.
    # "As an additional cost to cast this spell, sacrifice a creature" used to
    # be keyed here, by the instruction Sacrifice and Metamorphosis compile to.
    # It is a *cost*, so `derive_cast_spec` now reads it off `cast_costs` and
    # every card printing the phrase gets the picker — Village Rites and
    # Goremand buy nothing with it and were being offered no choice at all.
    # --- kinds that reach the picker through an activated ability -----------
    #
    # Each of these resolves through `resolve_target_permanent(game, context)` with
    # the default predicate — `p.is_creature` — so "creature" is what the code
    # that runs the ability accepts, not what the printed line says.
    "grant_banding_to_target": {"kind": "creature"},
    "grant_target_keyword_until_eot": {"kind": "creature"},
    "grant_target_ability_text": {"kind": "creature"},
    "add_named_counter_to_target": {"kind": "creature"},
    "grant_flying_and_delayed_destruction": {"kind": "creature"},
    "grant_unblockable_to_target": {"kind": "creature"},
    "steal_creature_while_tapped_and_weaker": {"kind": "creature"},
    "deny_regeneration_to_target": {"kind": "creature"},
    "pump_target_creature_until_eot": {"kind": "creature"},
    "grant_regeneration_to_target_creature": {"kind": "creature"},
    "mark_non_wall_target_to_attack": {"kind": "creature"},
    # Soltari Guerrillas: "…it deals that damage to **target creature**
    # instead." The redirect's *new recipient* is the target, which is the
    # opposite end from the two chosen-source rows above — those raise a picker
    # over every source including the stack, and this one over creatures. The
    # source needs no picker at all: it is the ability's own permanent.
    "redirect_source_damage_to_target_until_eot": {"kind": "creature"},

    # Effects that act on a *player*: the handler reads `context.target`,
    # a seat, and never looks at the battlefield. ``mill_target_player`` is not
    # among them — it names its recipient in the payload, so it is read by
    # ``_player_recipient_spec`` rather than answered flat.
    "look_at_target_hand": {"kind": "player"},
    "look_at_target_library_top": {"kind": "player"},
    "discard_target_cards": {"kind": "player"},
    # "Search **target opponent's** graveyard, hand, and library …"
    # (Necromentia). The searched player is a target chosen as the spell is cast
    # (CR 601.2c); the *card name* is chosen on resolution and is not a target at
    # all, which is why the kind is a plain player rather than something
    # card-shaped.
    "name_and_strip": {"kind": "player"},
    "name_then_reveal_top": {"kind": "player"},
    # ``target_loses_life`` is **not** here. Like its twin above it spells the
    # recipient in the payload, so it reads it — see ``_player_recipient_spec``.
    # "Exchange life totals with target opponent." (Mirror Universe.) The other
    # seat is a target chosen as the ability is activated (CR 602.2b); the
    # controller's own half is not chosen at all.
    "exchange_life_totals": {"kind": "player"},
    # Cuombajj Witches. Its handler delegates the controller's half to
    # `deal_damage`, which takes a player or a permanent; the opponent's half is
    # a pending choice made after resolution, not a target chosen here.
    "deal_damage_and_opponent_choice": {"kind": "any"},
    # Pyramids' second mode resolves through a `primary_type == "land"`
    # predicate.
    "shield_target_land_from_destruction": {"kind": "land"},
    # Cyclopean Tomb's handler refuses a Swamp outright
    # (`primary_type == "land" and not _is_swamp(p)`), so the exclusion belongs
    # to the kind rather than to the words "non-Swamp" appearing on the card.
    "add_mire_counter_to_target_land": {"kind": "land", "exclude_swamp": True},
    # Forcefield: "an unblocked creature of your choice would deal combat damage
    # to you" — the controller picks one of the attackers that got through.
    "grant_forcefield_shield": {"kind": "creature", "unblocked_attacker": True},
    # Jade Monolith picks twice: the creature it shields, and the damage source
    # whose damage is redirected. `requires_source` is what tells the UI to run
    # the second prompt.
    "jade_monolith_redirect": {"kind": "creature", "requires_source": True},
}


#: The wrapper kinds above, and the payload keys whose instructions they carry.
#: The same two ``_from_instructions`` descends into, and for the same reason
#: it gives — an effect written as two steps carries its targeting on the step
#: that targets.
#: The wrappers a targeting instruction can be *inside*, and where each keeps
#: its steps. `if_then` carries both arms for the reason `_from_instructions`
#: reads both: CR 601.2c chooses an ability's targets when it is activated,
#: whichever way the condition later falls. It was missing here while
#: `_from_instructions` handled it by hand, so the spec recursed into a
#: conditional branch and every other reader of this table stopped at the
#: wrapper — which is how Lesser Werewolf's "target creature blocking or blocked
#: by this creature" reached `legality.py` as an `if_then` with no filter.
_WRAPPER_STEP_KEYS = {
    "sequence": ("steps",),
    "may": ("action", "then"),
    "if_then": ("then", "else"),
}


def _nested_steps(instruction) -> tuple:
    """The instructions a wrapper carries, empty for anything else."""
    nested: tuple = ()
    for key in _WRAPPER_STEP_KEYS.get(instruction.kind, ()):
        nested += tuple(instruction.payload.get(key) or ())
    return nested


#: The condition payload keys whose value is a **player reference**, and the
#: picker each targeted spelling of one means. A condition may be the only place
#: a spell says "target" (Tithe), and a spec derived from the arms alone cannot
#: see it. Keyed by the word rather than by the condition kind: "target
#: opponent" means the same announcement whatever question is asked of it, and a
#: table per kind would have to grow an entry for every clause that ever takes a
#: seat.
_TARGETED_CONDITION_PLAYERS: dict[str, dict] = {
    "target_opponent": {"kind": "player", "opponents_only": True},
    "target_player": {"kind": "player"},
}


def _condition_target_spec(condition) -> dict | None:
    """The picker a condition announces, or None when it announces nothing.

    Only the seat, deliberately. A condition that counted *objects* would be
    describing a set rather than choosing one, and the only instances of the
    word "target" the pool prints inside a condition today name a player.
    """
    if not isinstance(condition, dict):
        return None
    spec = _TARGETED_CONDITION_PLAYERS.get(str(condition.get("who") or ""))
    if spec is not None:
        return dict(spec)
    # "If <a> and <b>" / "If <a> or <b>": the joined halves are conditions in
    # their own right, and a target inside one of them is still announced.
    for key in ("conditions", "parts", "all", "any"):
        for part in condition.get(key) or ():
            nested = _condition_target_spec(part)
            if nested is not None:
                return nested
    return None


def _from_instructions(instructions) -> dict | None:
    """The first spec any instruction in *instructions* describes.

    Recurses into `sequence` steps: an effect written as two steps carries its
    targeting on the step that targets (Psionic Blast's damage to any target,
    followed by its self-damage; Orcish Artillery's ability, the same shape),
    and stopping at the wrapper would leave an otherwise fully-described effect
    with no prompt.
    """
    slot = _first_described_slot(instructions)
    return slot[0] if slot is not None else None


def _first_described_slot(instructions) -> "tuple[dict, object] | None":
    """``(spec, instruction)`` for the first description in *instructions*:
    the spec :func:`_from_instructions` answers with, beside **the instruction
    that carries it**.

    One walk, two readers. The picker wants the spec; CR 601.2c's "is this
    target one the announcement *must* make?" wants the instruction, because
    the answer is that slot's own printed quantifier ("target" against "up to
    one target") and a spec does not keep it. Asking the program at large
    instead — every quantifier it carries, wherever it sits — answers about a
    different slot the moment a spell prints two (Primal Might: "Target
    creature you control … fights **up to one** target creature you don't
    control"), which is how the AI's reader and the engine's came to disagree
    about which spells need a target at all.

    **"Nothing to point at" is an answer about one step, not about the steps
    behind it.** A row answering ``{"kind": "none"}`` is the positive statement
    that its instruction chooses nothing ("this creature gains protection from
    black and from red until end of turn"), and it used to end the walk — so a
    sequence opening on one hid the target the next sentence announces ("…
    **Target opponent** gains 2 life", Questing Phelddagrif), the ability
    derived no picker and the client sent a bare activation. The same card's
    other two abilities open on a kind with no row at all and were read
    straight through to their target, which is the accident that made the
    difference a fact about which keyword was granted. So a "none" is kept as
    the answer of last resort: returned only when nothing behind it describes a
    choice.
    """
    nothing: "tuple[dict, object] | None" = None

    def chosen(slot):
        """*slot* when it describes a choice; None — remembering it — when it
        is the positive "nothing" answer, or no answer at all."""
        nonlocal nothing
        if slot is not None and slot[0].get("kind") == "none":
            if nothing is None:
                nothing = slot
            return None
        return slot  # chosen

    for instruction in instructions:
        # "…**target opponent** loses 2 life unless… You may repeat this
        # process any number of times." (Forbidden Ritual.) A repeated process
        # is a sequence with a decision wrapped round it, and the target is
        # announced once as the spell is cast (CR 601.2c) — every round uses
        # the seat the announcement chose — so the steps are read exactly as a
        # plain sequence's are. Left out, the spell derived no spec at all,
        # which is the value the client tests to decide whether to ask for a
        # target: the Roots class, through the door this round opened.
        # "**Target player** mills two cards. If two cards that share a color
        # were milled this way, repeat this process." (Grindstone.) The third
        # wrapper and the same reading for the same reason: the target is
        # announced once as the ability is activated (CR 602.2b) and every
        # round uses the seat the announcement chose. `picker_sweep` caught it
        # the round the kind was invented, which is the Roots class arriving
        # through the door a new wrapper opens.
        # "…destroy target creature you control unless you pay {3} and repeat
        # this process." (Crooked Scales.) The fourth wrapper and the same
        # reading for the same reason as the two repeats beside it: both
        # targets are announced once as the ability is activated (CR 602.2b),
        # and every round spends the ones the announcement chose.
        # "Repeat this process until …" (Tainted Pact's wrapper) is the fifth,
        # listed for the reason the others are and before any card needs it: a
        # targeted round inside it announces once (CR 601.2c), and a wrapper
        # this did not open would derive no spec — the Roots class again.
        if instruction.kind in (
            "sequence", "repeat_optional_process", "repeat_process_while",
            "repeat_process_on_request", "repeat_process_until",
        ):
            nested = _first_described_slot(instruction.payload.get("steps") or ())
            if chosen(nested) is not None:
                return nested
            continue
        if instruction.kind == "if_then":
            # "If you lose the flip, counter target artifact spell you control."
            # (Goblin Artisans.) A branch that may not run still *chooses* — CR
            # 601.2c and 602.2b pick targets as the ability is activated,
            # whichever way the coin lands — so both arms are read, and an
            # ability whose only targeting sits behind a conditional gets its
            # prompt rather than the picker's silent fallback.
            nested = _first_described_slot(
                tuple(instruction.payload.get("then") or ())
                + tuple(instruction.payload.get("else") or ())
            )
            if chosen(nested) is not None:
                return nested
            # "If **target opponent** controls more lands than you, …" (Tithe.)
            # The instance of the word "target" is in the *condition*, and
            # CR 601.2c does not care which half of the sentence it appears in —
            # the spell announces the opponent as it is cast, and nothing in the
            # arms describes anybody. Read after the arms, because a card whose
            # arms target as well announces those (this one's do not), and
            # because the arms are what the effect acts on.
            #
            # Without it Tithe compiled supported, carried no hollow line and
            # claimed every printed sentence, and derived a cast spec of None —
            # the exact value the client tests to decide whether to ask for a
            # target, so it sent a bare cast and the engine refused it. The
            # Roots class, arriving through a door nothing had come through
            # before.
            condition_spec = _condition_target_spec(instruction.payload.get("condition"))
            if condition_spec is not None:
                return condition_spec, instruction
            continue
        if instruction.kind == "unless_player_pays":
            # "Unless an opponent pays {2}, gain control of **target artifact**
            # …" (Scarwood Bandits). The ability's target sits on the *unpaid*
            # branch, and CR 601.2c picks it as the ability is activated —
            # before anyone is offered the cost — so this branch is read where
            # an offer's declined branch deliberately is not.
            nested = _first_described_slot(
                tuple(instruction.payload.get("unpaid") or ())
                + tuple(instruction.payload.get("paid") or ())
            )
            if chosen(nested) is not None:
                return nested
            continue
        if instruction.kind == "choose_one":
            # A **choice made before the targets** (CR 601.2b/602.2b: modes
            # first, then targets), so the modes are read only when the choice
            # cannot change the answer.
            #
            # Barbarian Guides is why: "Choose a land type. Target creature you
            # control gains snow landwalk of the chosen type…" lowers to one
            # mode per land type, and all eighteen carry the *same* target
            # description, because the type is what varies and the creature is
            # not. Stopping at the wrapper left the whole ability with no
            # prompt — and, because the handler enforces the printed
            # "you control" against a target nobody chose, doing nothing at all.
            #
            # Non-uniform modes deliberately answer None. Essence Filter and
            # Relic Bind choose different things in each mode, and the mode is
            # settled first: the per-mode reader
            # (``graveyard_target_spec(..., mode_index=)``) is what answers
            # those, and collapsing them to the first mode's spec would offer a
            # picker for a mode the player had not chosen.
            modes = instruction.payload.get("modes") or ()
            described = [
                _first_described_slot((mode.get("instruction"),))
                if isinstance(mode, dict) and mode.get("instruction") is not None
                else None
                for mode in modes
            ]
            specs = [slot[0] if slot is not None else None for slot in described]
            if specs and all(spec == specs[0] for spec in specs[1:]):
                if chosen(described[0]) is not None:
                    return described[0]
            continue
        if instruction.kind == "may":
            # "**Target opponent** may ante the top card of their library."
            # (Amulet of Quoz.) The offer's own target, which is the *seat being
            # offered* rather than anything the branches name — so it is read
            # off this instruction before its branches are, the way every
            # non-wrapper instruction is read before nothing at all.
            #
            # ``actor`` cannot answer this: the reference reader spells "an
            # opponent" ``opponent`` and "target opponent" ``target_opponent``
            # precisely so the two do not share a kind, but reading the actor
            # here would put that distinction in two places. The lowering
            # attaches the ordinary ``targets`` description instead, so the
            # picker learns it the way it learns every other target.
            own = _from_targets_payload(instruction.payload.get("targets"))
            if own is not None:
                return own, instruction
            # An optional action still targets — "you may tap or untap target
            # creature" names a creature whether or not the offer is taken.
            #
            # `action` and `then` only. `otherwise` is the *declined* branch and
            # `reflexive` is a separate ability (CR 603.12) that chooses its own
            # targets when the payment creates it; reading either here would
            # report this instruction as targeting something it never picks —
            # and for the reflexive branch, at a moment when the choice has not
            # been offered yet.
            nested = _first_described_slot(
                tuple(instruction.payload.get("action") or ())
                + tuple(instruction.payload.get("then") or ())
                # …and the **declined** branch, last. "Destroy target creature
                # unless its controller pays life equal to its toughness"
                # (Essence Vortex) puts the whole spell on this branch, and the
                # creature is a target of the *spell*: CR 601.2c picks it as the
                # spell is announced, before anybody is offered the payment, so
                # a picker that skipped this branch would leave the spell with
                # no prompt and the destruction pointed at nothing.
                #
                # Read after the two above rather than beside them, so an offer
                # that targets on both sides still answers with the branch it
                # takes. ``reflexive`` stays out: CR 603.12 makes it a separate
                # ability that chooses its own targets when the payment creates
                # it, which has not happened yet.
                + tuple(instruction.payload.get("otherwise") or ())
            )
            if chosen(nested) is not None:
                return nested
            continue
        spec = _from_instruction(instruction)
        if spec is not None and chosen((spec, instruction)) is not None:
            return spec, instruction

    return nothing


#: The divisions whose spec carries the quantity being divided.
#:
#: CR 601.2d's "as you choose" needs it so the picker can ask for a division
#: that totals it. The two the *card* divides need it for a different reader and
#: the same reason: ``ai_divisions._divided_announcement_total`` asks "how much is
#: there", and a spell whose answer is 0 has no lawful announcement at all — so
#: Cone of Flame, whose 6 is printed and needs no asking, was skipped by the
#: policy every turn it was in hand.
_SIZED_DIVISIONS = frozenset({CHOSEN}) | CARD_DIVIDED


def _sized_division(described: dict | None, instruction) -> dict | None:
    """*described* with the quantity its division divides, where it describes
    one (``_SIZED_DIVISIONS``) — otherwise unchanged.

    **How much there is to divide**, so the picker can ask for a division that
    totals it (CR 601.2d). Read off the payload here rather than copied into
    the `targets` description at lowering: the amount is the instruction's own
    field, and a second copy beside the target description is a second thing
    to keep in step. ``amount`` for damage and a prevention shield, ``count``
    for a distributed counter placement — CR 601.2d covers them with one
    sentence, and each instruction family spells its quantity with the word
    its own handler reads. A variable ("x") is no total yet: the picker learns
    it once the caster announces X, or the card defines one.
    """
    if described is None or described.get("division") not in _SIZED_DIVISIONS:
        return described
    amount = instruction.payload.get("amount", instruction.payload.get("count", 0))
    if isinstance(amount, int) and not isinstance(amount, bool):
        described["division_total"] = amount
    described["division_x_bonus"] = int(
        instruction.payload.get("amount_bonus", 0) or 0
    )
    return described


def _from_instruction(instruction) -> dict | None:
    """The spec one instruction describes, or None when it describes none."""
    # **A step of a several-role announcement answers with the announcement.**
    # "Counter target spell **and** Suffocating Blast deals 3 damage to target
    # creature" stamps one ordered ``roles`` list on both steps, and the first
    # of them is a counter — a kind with a payload reader of its own two lines
    # down, which pre-empts the generic ``targets`` reading. Left to it, the
    # line's picker was the counter's alone: a stack picker, the creature
    # never asked for. A stamped step (``payload_own_role``) says which slot
    # of a shared announcement it spends, so the announcement is the answer
    # whatever kind carries it; every instruction that names no role falls
    # through exactly as before.
    if payload_own_role(instruction.payload) is not None:
        announced = _from_targets_payload(instruction.payload.get("targets"))
        if announced is not None:
            return announced
    # A kind with several specs settles its own case first, because it is the
    # only reader that knows how to combine its payload with its `targets`
    # description — a colour-restricted counterspell carries both, and the
    # generic targets reading would drop the colour.
    from_payload = _KIND_TO_SPEC_FROM_PAYLOAD.get(instruction.kind)
    if from_payload is not None:
        # …and a division it describes is sized like any other. "Prevent the
        # next 5 damage … to any number of targets, **divided as you choose**"
        # (Remedy) is a kind with a spec reader of its own, so it returned from
        # here before the sizing below ran: the spec said "divided, as you
        # choose" and not how much. Both of its readers then had nothing to
        # divide — the browser fell back to asking for an X the card does not
        # print, and `ai_divisions._divided_announcement_total` read 0, which is
        # "no lawful announcement", so no AI seat ever cast Remedy or Pollen
        # Remedy.
        return _sized_division(from_payload(instruction.payload), instruction)
    described = _from_targets_payload(instruction.payload.get("targets"))
    if described is not None:
        return _sized_division(described, instruction)
    # **A ``type_filter`` is only a picker for a kind that picks.** The key
    # names the class an instruction is *about*, and what that class is for
    # depends entirely on the kind holding it: "destroy target permanent"
    # narrows the one object the caster chooses, while "destroy all black
    # creatures" names every object the effect touches and chooses none of them
    # (CR 115.1a — an instant or sorcery is targeted only where its ability
    # says "target"). Read unkeyed, the two are the same payload, so the reader
    # guessed "picker" and a sweep reported a target it never chooses.
    if instruction.kind in _TYPE_FILTER_NAMES_THE_TARGET:
        spec = _spec_from_type_filter(instruction.payload)
        if spec is not None:
            return spec
    # **An instruction acting on a recorded set chooses nothing.**
    # ``permanents_from`` names what an earlier step of this same resolution
    # put in the scratchpad — the creature a ``choose_permanent`` prompt was
    # answered with, the permanents a tap recorded — and CR 601.2c chose none
    # of them: a target is announced when the spell or ability goes on the
    # stack, and these objects were not known then.
    #
    # Asked here rather than in each kind's own row because it is a property of
    # the payload and not of the kind: the very same ``add_counter_to_target``
    # is a target on Dwarven Weaponsmith and a back-reference on Thelon's
    # Chant. Read as a target, the Chant's trigger acquired one it never had —
    # and a trigger whose only target is illegal is removed from the stack
    # (CR 603.3c), which on a board with no creature to shrink is the whole
    # ability gone instead of three damage.
    #
    # After the two readings above on purpose: an instruction carrying a real
    # ``targets`` description settles on that, and none in the pool carries
    # both.
    if instruction.payload.get("permanents_from"):
        return None
    # **…and so does one acting on the firing event's own object.** "Whenever a
    # permanent becomes tapped, put a wind counter on **it**" (Freyalise's
    # Winds), "…a creature or land becomes tapped, put an hourglass counter on
    # it" (Temporal Distortion). ``on_event_subject`` is the lowering's record
    # that the pronoun names what the event was about, found by the id the fire
    # site froze (CR 603.10) — the paragraph above with the record held by the
    # trigger instead of by the resolution, and with the same consequence:
    # read as a target, the trigger asked for a creature nobody was choosing,
    # and on a board with **no creature** CR 603.3c removed it from the stack,
    # so tapping a land under either enchantment put no counter on it.
    if instruction.payload.get("on_event_subject"):
        return None
    by_kind = _KIND_TO_SPEC.get(instruction.kind)
    return dict(by_kind) if by_kind is not None else None

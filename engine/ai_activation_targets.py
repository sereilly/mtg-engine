"""Where an ability of the seat's **own** is aimed: which seat, which
permanent, which chain of roles.

The main-phase chooser (``ai_abilities.choose_activation_action``) aims each
target on the side its effect wants (:func:`_activation_target_side`, read
step by step off the program), walks a roles chain
(:func:`_choose_activation_role_targets`), names the creature an Equipment
moves onto (:func:`_choose_equip_target`) and the seat an ability names
(:func:`_choose_target_for_instruction`, which the foreign chooser asks too).

Split out of ``ai_abilities`` (kg5) by subject: that module gates and plans a
proposal, this one aims it.
"""

from __future__ import annotations

from .ai_slot_sides import ability_role_target_sides
from .ai_scoring import choose_attack_target
from .ai_target_sides import (
    ability_seat_side,
    ability_target_side,
    instruction_target_side,
    named_counter_marks_for_harm,
    toll_effect_side,
    untaps_its_target,
)
from .ai_targets import _aura_harms_its_host
from .ai_valuation import is_mana_ability, source_becomes_an_aura
from .ai_weighed_cast import _effect_steps
from .game import Game
from .models import Permanent
from .oracle import OracleInstruction, compile_card_oracle
from .target_roles import OPTIONAL_ROLE
from .targeting import spec_roles, usable_activated_abilities


def _required_activation_target(
    game: Game, player_index: int, permanent_index: int, target,
    ability_index: int = 0,
) -> int | None:
    """The slot on seat *target* a one-target ability must be aimed at for
    its activation to obey a target requirement in force, or None when there
    is none there. `ai_cast_gates._aimed_under_target_requirements` for an activation: the
    picker's own ``required_targets``, on the board the policy already chose.
    """
    from .target_requirements import one_slot

    spec = game.activation_target_spec(
        player_index, permanent_index, ability_index=ability_index,
    )
    if not one_slot(spec):
        return None
    return next(
        (
            entry["index"] for entry in spec.get("required_targets") or ()
            if entry.get("seat") == target
        ),
        None,
    )


def _untaps_only(instruction) -> bool:
    """Whether every step of *instruction* untaps its target — the reader a
    trigger's target is aimed by too (``ai_target_sides.untaps_its_target``),
    so an activation and a trigger printing the same untap read it alike."""
    return untaps_its_target(instruction)


#: The kinds whose effect lasts only "for as long as this … remains tapped"
#: (``engine/source_tapped_effects.py``).
_HELD_WHILE_SOURCE_TAPPED = frozenset({
    "pump_target_while_source_tapped",
    "grant_target_keyword_while_source_tapped",
})


def _held_by_its_tapped_source(ability) -> bool:
    """Whether *ability* taps its source to start an effect on a target that
    lasts only while the source stays tapped."""
    if not getattr(ability.cost, "requires_tap", False):
        return False
    return any(
        step.kind in _HELD_WHILE_SOURCE_TAPPED
        for step in _effect_steps(ability.instruction)
    )


def _activation_target_side(permanent: Permanent, instruction) -> str | None:
    """Whose permanent an own-seat ability's object target should be — "you",
    "opponent", or None for no preference.

    **Read step by step** (`ai_target_sides.ability_target_side`), the reading the
    foreign chooser (`ai_foreign_activations`) already took. This asked
    `instruction_target_side` of the top-level instruction, and a
    ``sequence`` / ``may`` wrapper has no side, so an ability whose effect is
    two steps fell back to "the biggest creature on either board": Bullwhip
    pinged and Serrated Biskelion shrank the AI's own biggest creature, Power
    Matrix and Ivy Seer pumped the opponent's, and Wishmonger gave the
    opponent's protection. Measured over both manifest
    roles with a creature of each size on each board: 47 abilities aimed at
    the wrong seat in one board or the other. The top-level reading stays as
    the fallback for a leaf whose target is not a ``targets`` payload.

    An ability that turns its source into an Aura (the Licids) is aimed as
    that Aura would be cast (`_aura_harms_its_host`): its attach step reads
    "you" for an Equipment's reason, and Calming Licid's "can't attack" or
    Dominating Licid's "you control enchanted creature" belong on an
    opponent's creature.
    """
    if source_becomes_an_aura(instruction):
        return "opponent" if _aura_harms_its_host(permanent.effective_card) else "you"
    # "{T}: Put a fuse counter on target creature." (Bomb Squad.) A named
    # counter reads as a gift by category, and the card's own state trigger
    # says this one is a death sentence — the Licids' case again: which board
    # the target belongs on is what the card's *other* text does with it.
    if named_counter_marks_for_harm(permanent.effective_card, instruction):
        return "opponent"
    # …and "Return target creature to its owner's hand unless its controller
    # pays {1}" (Crystal Shard, Erratic Portal): the toll's unpaid branch names
    # no target payload, so it is read last, by its own family
    # (`ai_target_sides.toll_effect_side`).
    return (
        ability_target_side(instruction) or instruction_target_side(instruction)
        or toll_effect_side(instruction)
    )


def _keyword_walk_order(game: Game, ability) -> list:
    """The words to try for a "Choose flying, first strike, trample, or
    shadow" cost (Phyrexian Splicer), best first: None — the engine's own
    default (``Game.announced_chosen_keyword``), so an activation the default
    serves is proposed exactly as it always was — then every other printed
    word in order. ``[None]`` for an ability whose cost chooses no word."""
    options = tuple(
        getattr(getattr(ability, "cost", None), "chosen_keyword_options", ()) or ()
    )
    if not options:
        return [None]
    default = game.announced_chosen_keyword(ability)
    return [None, *(word for word in options if word != default)]


def _choose_activation_role_targets(
    game: Game, player_index: int, permanent_index: int,
    side: str | None = None, ability_index: int = 0,
    chosen_keyword: str | None = None,
) -> "list[dict] | None":
    """One object per **role** for an activated ability, or None when no legal
    chain exists.

    ``ai_slot_targets._choose_role_targets``' twin on the activation side, and it is a twin
    rather than a shared body for the reason the two specs are derived
    separately: a spell's roles come from the card and an ability's from *that
    ability* (CR 602.2b), so the walks start from different calls. What they
    share is the policy — take the first option at each level — and it is safe
    for that function's stated reason: a first choice that leaves a later role
    with nothing is not in the list ``_role_target_walk`` returns.

    The answer is in the wire's own shape (``target_role_refs``) because a role
    here may be a card in a graveyard, which has no permanent id to send.

    **A role may also be a seat**, and this walk had no arm for one: "Target
    **opponent** reveals a card at random from their hand. **Target creature**
    gets +X/+X …" (Planeswalker's Favor, Scorn), "Prevent the next 2 damage …
    to target creature. **Target opponent** may draw a card." (Soldevi
    Heretic). A pick of kind ``"player"`` is neither a permanent nor a card, so
    it fell to the permanent branch, found nothing at that seat's slot ``None``
    and answered "no legal chain" — three abilities, the only three in the pool
    that announce a seat in a roles chain, that no AI seat ever activated.

    *side* is which board the ability's object role is aimed at
    (``_activation_target_side``), and with a seat role in the chain it is no
    longer optional: the first option at the permanent level is the first
    board in seat order, so without it Scorn's -X/-X would land on the
    activator's own creature whenever the activator sits first. A level with
    no pick on the wanted side is "no legal chain", the single-target block's
    rule above and for its reason — **unless the role is optional**
    (``target_roles.OPTIONAL_ROLE``), where the chain stops there instead.

    *chosen_keyword* walks the tree for that word of a "Choose flying, …"
    cost (``valid_targets_by_keyword``); None walks the default word's.
    """
    offered = game.activation_target_spec(
        player_index, permanent_index, ability_index=ability_index,
    )
    options = (
        (offered.get("valid_targets_by_keyword") or {}).get(chosen_keyword)
        if chosen_keyword is not None
        else offered.get("valid_targets")
    ) or []
    optional = frozenset(
        position for position, role in enumerate(spec_roles(offered))
        if role.get(OPTIONAL_ROLE)
    )
    # **One side per role, not one for the chain** — the derivation the cast
    # side asks (`ai_slot_sides.role_target_sides`), over this ability's own
    # roles. "Target creature with the chosen ability loses it and **another
    # target creature** gains it" (Phyrexian Splicer) is two roles on two
    # boards, and a single side — or none, the first option at each level —
    # named two of the activator's own creatures: the seat paid {2} to move
    # its own flying from one of its creatures to another. *side* stays the
    # answer for a role the derivation gives none (the three seat-role
    # chains it was written for).
    #
    # The permanent as it **is** (``effective_card``), which is the card the
    # picker three lines up compiled: read off the printed one, a Clone of a
    # Splicer was offered the Splicer's two roles and given a side for neither.
    #
    # **The ability at *ability_index***, the one the picker above was asked
    # about: this read the first, which every ability this walk was asked for
    # was until a permanent's later abilities were weighed (kg4).
    source = game.permanent_at(player_index, permanent_index)
    said = source.effective_card if source is not None else None
    usable = usable_activated_abilities(compile_card_oracle(said)) if said is not None else []
    ability = usable[ability_index] if 0 <= ability_index < len(usable) else None
    sides = ability_role_target_sides(said, ability) if ability is not None else ()

    def ref_of(pick: dict) -> "dict | None":
        if pick.get("kind") == "player":
            return {"seat": pick.get("seat")}
        if pick.get("kind") == "graveyard":
            return {
                "graveyard_seat": pick.get("seat"),
                "graveyard_index": pick.get("index"),
            }
        permanent_id = game.permanent_id_of(
            game.permanent_at(pick.get("seat"), pick.get("index"))
        )
        return {"permanent_id": permanent_id} if isinstance(permanent_id, int) else None

    def chain(level: list[dict], position: int) -> "list[dict] | None":
        """The first chain from *level* on whose every role is on the board
        its step wants. Backtracks, because a side makes a first pick able to
        strand a later role the unfiltered walk had an answer for."""
        own = sides[position] if position < len(sides) else None
        wanted = own or side
        # A role whose **own** step gives it a side and that a player can
        # answer — CR 115.4's "any target" (Shieldmage Advocate's shield) —
        # holds its seat options to that side too: the first option is the
        # first seat in order, so an activator sitting second shielded its
        # opponent. Only on the role's own side, never the chain's fallback,
        # because a seat role ("target opponent") has none of its own and its
        # options are already the seats the role admits.
        seats_sided = own in ("you", "opponent")
        if wanted in ("you", "opponent") and any(
            option.get("kind") == "permanent"
            or (seats_sided and option.get("kind") == "player")
            for option in level
        ):
            level = [
                option for option in level
                if not (
                    option.get("kind") == "permanent"
                    or (seats_sided and option.get("kind") == "player")
                )
                or (option.get("seat") == player_index) == (wanted == "you")
            ]
        for pick in level:
            ref = ref_of(pick)
            if ref is None:
                continue
            rest = pick.get("next") or []
            if not rest:
                return [ref]
            tail = chain(rest, position + 1)
            if tail is not None:
                return [ref, *tail]
        return [] if position in optional else None

    return chain(options, 0) if options else None


def _choose_equip_target(game: Game, player_index: int, equipment) -> int | None:
    """The battlefield index of the creature *equipment* should be moved onto,
    or None when it is already on the best one (or there is none).

    The biggest creature that can attack — power first, then toughness — among
    the ones the Equipment may legally equip, asked of the same legality the
    engine enforces (``engine/equipment.py``) so the AI never activates an
    equip the engine then refuses. Summoning-sick creatures are not excluded:
    an Equipment moved onto one now is on it when it can attack next turn, and
    the +1/+1 blocks just as well meanwhile.
    """
    from .equipment import equip_refusal, equipped_creature

    player = game.players[player_index]
    candidates = [
        (idx, perm)
        for idx, perm in enumerate(player.battlefield)
        if perm.is_creature and equip_refusal(game, equipment, perm) is None
    ]
    if not candidates:
        return None
    best_index, best = max(
        candidates,
        key=lambda pair: (pair[1].effective_power, pair[1].effective_toughness, -pair[0]),
    )
    if equipped_creature(equipment) is best:
        return None
    return best_index


def _choose_target_for_instruction(instruction: OracleInstruction, caster_index: int, game: Game) -> int:
    if is_mana_ability(instruction):
        # Mana goes to its controller's pool; the ability has no other target.
        return caster_index
    if instruction.kind == "attach_source_to_target":
        # "Target creature you control" — the equip's creature is the
        # activator's own (CR 702.6a).
        return caster_index
    # A gift names its own seat: "target player gains 3 life", "target player
    # draws a card", "prevent the next 1 damage that would be dealt to any
    # target". *Which* effects those are is `ai_target_sides.ability_seat_side`'s
    # reading of the compiled program — this line used to name three kinds, two
    # of which nothing compiles, so a life gain and every shield went to an
    # opponent.
    if ability_seat_side(instruction) == "you":
        return caster_index
    # "deal_damage"/"destroy_target"/etc., and the fallback for any other
    # proactive effect: target an opponent (MVP heuristic, see
    # choose_attack_target — lowest life among living opponents).
    return choose_attack_target(game, caster_index)

"""Lowering a sentence whose whole content is a **choice of targets**
(CR 601.2c).

"Choose target creature." "Choose target opponent." "Choose two target
creature cards in your graveyard." "Choose X target attacking creatures." Each
does nothing on resolution — the choosing happened as the spell was cast — and
each lowers to an instruction anyway, so that ``engine/targeting.py`` raises the
picker off the compiled program rather than off a second reading of the text.
The four kinds differ in what the picker enumerates: a seat, cards in one
graveyard, a set of permanents, one permanent.

Split out of ``lowering/delayed.py`` at Torment's Phase 0, when that module had
sat at exactly the thousand-line guard since Apocalypse. The line is not new.
The parse side drew it first, when ``grammar/choices.py`` left
``grammar/delayed.py`` with the sentence "a shared reason is not a shared
subject", and this takes that module's name so the mirror re-forms rather than
forks. What is left in ``delayed`` lowers a sentence that arranges for
something *later*. What is here lowers a sentence that is nothing but an
announcement.

The shared reason was Visions' second wave's: each "choose" is "the first
sentence of a two-sentence spell whose second sentence is the delayed half, so
the pair is read together or not at all". Measured at this split, that holds
for 7 of the 23 shipped cards whose compilation reaches this lowering:
Reincarnation, both Glyphs, Venomous Breath, Dwarven Sea Clan, Soldevi Sentry
and Winter's Chill. The other 16 print no delay — the five Oaths, the five
Keepers, Victimize, Retribution, Barrin's Spite, Cannibalize, Samite Elder and
Silhouette. And where the pair *is* read together, it is read on the parse
side, where ``grammar/choices.py``'s binder probe asks the delayed production.
Each lowering is reached from ``by_node`` on its own node, and the two modules
never read each other.

Autumn Willow's shroud waiver travelled with this at Visions and did not come
here. It changes who *may* choose rather than choosing, so it went to
``permissions``.

A lowering-only family, like ``delayed`` and for the same reason:
``ChooseTarget`` sits in ``ast/stack.py`` beside ``ModalNode``, because a target
is chosen while the object goes onto the stack (its docstring says so).

One spelling of the same announcement lowers elsewhere, and stays there.
"**You** choose target creature an opponent controls" (Mogg Assassin) parses as
``ast.ChoosePermanent``, the pick a resolution makes, and
``attachments._lower_announced_choice`` lowers it to ``choose_target_permanent``
because the chooser it names is CR 601.2c's default. ``statement_dispatch``
tells that reading from the prompt by a decision rather than a row, so it lives
with the prompt it is told apart from.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._events import CHOSEN_PLAYER
from ._common import (
    _describe_several_card_targets, _describe_several_targets,
    _describe_targets, _names_several_targets, _restrictions_beyond,
)


def _lower_choose_target(node: ast.ChooseTarget) -> tuple[OracleInstruction, ...]:
    """"Choose target creature." — the targeting half of a two-sentence spell.

    The instruction does nothing on resolution and that is the whole of it:
    CR 601.2c chooses the target as the spell is cast, and the sentence prints
    no effect. It exists so ``engine/targeting.py`` can derive what the spell
    targets from the compiled program, which is where every other card's
    picker comes from — the alternative is a second reading of the oracle text.
    """
    payload: dict[str, object] = {}
    if isinstance(node.subject, ast.PlayerRef):
        # "Choose target opponent." (Soldevi Sentry.) The player form, and a
        # different instruction rather than the same one over a different noun:
        # the object form's handler resolves a *permanent*, and it also records
        # nothing — where this one writes the chosen seat under the one key
        # "that player" is ever read from, because the sentence naming that seat
        # is a delayed ability created two sentences later and by then the
        # resolution that chose is over.
        _describe_targets(payload, node.subject)
        if "targets" not in payload:
            raise LoweringError("this 'choose' names no player", node=node)
        if node.chooser is not None:
            # "**That player** chooses target player who…" (the Oaths). The
            # seat the card says announces the target, carried into the same
            # description the picker reads — CR 601.2c's default is the
            # ability's controller, and under those cards' trigger that is a
            # different player from the one printed. Refused rather than
            # dropped for every other referent: a chooser the announcement
            # cannot resolve would silently fall back to the default, which is
            # the one player the card says does *not* pick.
            if node.chooser.kind != "that_player":
                raise LoweringError(
                    f"nothing announces a target for the {node.chooser.kind}",
                    node=node,
                )
            if payload["targets"].get("opponents_only"):
                # "Target **opponent**" is a narrowing the enumerator applies
                # against the seat that *announces* (CR 601.2c, CR 102.2), and a printed
                # chooser is precisely a card saying that seat is somebody
                # else. Enforced as it stands, the word would exclude the
                # ability's controller while the card excludes the chooser —
                # two different players. Refused rather than resolved to
                # either, exactly as the two-seat phrases elsewhere in this
                # package refuse.
                raise LoweringError(
                    "a printed chooser and \"target opponent\" name the "
                    "opponent of two different seats",
                    node=node,
                )
            payload["targets"]["chooser"] = node.chooser.kind
        payload["result_key"] = CHOSEN_PLAYER
        return (OracleInstruction("choose_target_player", "", payload),)
    # "Choose **two target creature cards in your graveyard**." (Victimize.)
    # The announcement over a *zone* rather than over a battlefield, which is
    # why it is its own kind: everything below describes permanents through
    # ``_filter_payload``, and that builder refuses a card and a non-battlefield
    # zone outright — reading this phrase there would point the picker at the
    # battlefield for a spell that names a graveyard.
    #
    # Like every "choose" here it does nothing on resolution. The cards travel
    # on the stack item's own target list for the whole resolution, so the
    # sentence that returns them reads the announcement directly; this
    # instruction exists so `engine/targeting.py` can derive the picker from the
    # compiled program, which is where every other card's comes from.
    subject = node.subject
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.filter.is_card
        and subject.filter.zone == "graveyard"
    ):
        if subject.filter.zone_owner is None or subject.filter.zone_owner.kind != "you":
            raise LoweringError(
                "the graveyard announcement reads the chooser's own pile",
                node=node,
            )
        if _restrictions_beyond(
            subject.filter, frozenset({"is_card", "zone", "zone_owner", "card_types"})
        ):
            raise LoweringError(
                "the graveyard announcement cannot read that card phrase",
                node=node,
            )
        if len(subject.filter.card_types) != 1:
            raise LoweringError(
                "the graveyard announcement reads one card type", node=node
            )
        _describe_several_card_targets(payload, subject)
        # The narrowing on the *instruction* as well as in the description, in
        # the key ``graveyard_card_matches`` reads — the picker, the CR 601.2c
        # gate and the sentence behind this one all ask that one predicate, and
        # a description carrying no filter (which is this shape's contract) has
        # nowhere else to put it.
        payload["any_card"] = False
        payload["card_type"] = subject.filter.card_types[0]
        return (OracleInstruction("choose_target_cards", "", payload),)
    if _names_several_targets(node.subject):
        # "Choose **X target attacking creatures**." (Winter's Chill.) A *set*,
        # and a different instruction rather than the same one with a count:
        # the singular handler resolves one permanent and the loop behind this
        # sentence has to walk every one of them, so the several-target form
        # records what it chose. Recording is the whole of what it does — the
        # targets were chosen as the spell was cast (CR 601.2c) — but nothing
        # else in the resolution can say which attacking creatures those were.
        _describe_several_targets(payload, node.subject)
        if node.subject.same_controller:
            # "…**controlled by the same opponent**" (Retribution). A relation
            # between the targets, so it rides the *description* the picker and
            # the CR 601.2c gate read rather than the filter every matcher
            # tests one permanent against — no such matcher could answer it.
            payload["targets"]["same_controller"] = True
        return (OracleInstruction("choose_target_permanents", "", payload),)
    _describe_targets(payload, node.subject)
    if "targets" not in payload:
        raise LoweringError("this 'choose' names no target", node=node)
    return (OracleInstruction("choose_target_permanent", "", payload),)

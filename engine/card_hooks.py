"""Name-keyed registries for card-specific behavior.

Most cards should be handled generically by the parser (engine/grammar) and
effect handlers (engine/handlers). When a card needs truly bespoke logic that
no generic instruction covers, register it here instead of hardcoding the card
name inside engine internals. This keeps per-card behavior in one place and
lets the card pool grow without touching the core rules code.

Cast triggers used to live here as two name-keyed registries, covering six
cards whose conditions the oracle compiler already understood — they were
name-keyed only because nothing dispatched "whenever a player casts a … spell"
and because "you may pay {N}" had no generic representation. Both gaps are
closed: the condition's colour is captured into its payload and dispatched by
``engine/events.py``, and the optional cost is an ordinary ``may`` instruction.
Prefer that route before adding a registry entry here.

Hook registries:
- CARD_LINE_INSTRUCTIONS — the instruction one printed *line* of one card
                        compiles to, when that line is a single card's text
                        rather than a template. Read by engine/oracle.py.
- ON_SELF_RESOLVED    — fired when the named instant/sorcery itself resolves
                        (keyed by the resolving card's own name), for bespoke
                        effects the single compiled instruction can't express.
- ON_SPELL_COUNTERED  — fired after the named card counters a spell (keyed by
                        the counterspell's own name).
- ON_LEAVE_BATTLEFIELD — fired when the named permanent is put into a graveyard
                        from the battlefield (keyed by the permanent's name).
- DRAW_STEP_MODIFIERS — the skip-your-draw-for-protection behavior (Island
                        Sanctuary), consumed by engine/phases/draw_step. Untap
                        restrictions and symmetric bonus draws left this file:
                        they are templates, derived from oracle text by
                        engine/untap_restrictions.py and
                        engine/draw_step_modifiers.py.
Cost taxes left this file too: "<colour> spells cost {N} more to cast" is a
template, derived from oracle text by engine/cost_modifiers.py. So did the
land-tapping triggers (Mana Flare, Gauntlet of Might, Lifetap) — the compiler
now produces their conditions, so they are ordinary triggered abilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .auras import detach_aura
from .land_types import end_land_type_change
from .models import next_permanent_id
from .oracle_types import OracleInstruction
from .mana_payment import generic_cost, total_pips

if TYPE_CHECKING:
    from .game import Game
    from .game_types import StackItem
    from .models import CardDefinition, Permanent, PlayerState

SelfResolvedHook = Callable[["Game", "PlayerState", "CardDefinition", int, "int | None"], None]
SpellCounteredHook = Callable[["Game", "CardDefinition", "StackItem"], None]
LeaveBattlefieldHook = Callable[["Game", "PlayerState", "Permanent"], None]


# --------------------------------------------------------------------------
# Per-line instructions for texts that are one card, not a template
# --------------------------------------------------------------------------
#
# `engine/parsing/` is deleted. Most of what it claimed was templating and
# moves to a grammar production; the rest is a *single card's sentence* wired to
# a handler written for that card — Chaos Orb's flip, Camouflage's blocker
# piles, Shahrazad's subgame. The audit found 133 of its 168 rules were literal
# substring matches, several encoding a whole card's text, and a grammar
# production for one of those would be the same substring match wearing a
# grammar hat: it would report the sentence as *understood* while claiming
# nothing another card could ever share.
#
# So they come here instead, where a card name is what the file is for. This is
# not new coverage and not a regression — it is the reading `engine/parsing/`
# already had, moved to the registry that says out loud that it is per-card.
#
# **The entry bar is that no second card, real or plausibly printable, shares
# the shape.** A sentence two cards could carry belongs in `engine/grammar/`,
# where the second card gets it for free. When a line here grows a production,
# its entry goes: the grammar is consulted first (engine/oracle.py), so a stale
# entry would be dead rather than wrong — and `tests/engine/test_card_lines.py`
# fails on one, because an entry that stops being load-bearing is an entry
# nobody would notice was lying.
#
# Keys are the line as `oracle.normalize_creature_line` renders it: lowercased,
# reminder text in parentheses removed, whitespace collapsed, trailing stop
# dropped. The guard test builds them from the pool's own cards, so a key that
# no longer matches a printed line fails rather than silently never matching.


@dataclass(frozen=True)
class CardLine:
    """What one printed line of one card compiles to.

    *effect_kind* is the label the legacy rule reported (``activated_prevent``,
    ``upkeep_effect``, …). It feeds reporting — ``SimulationResult``,
    ``scripts/support_report.py`` — rather than dispatch, and is carried here so
    deleting the rule that produced it does not silently re-bucket the card.
    """

    instruction: OracleInstruction
    effect_kind: str


def _line(kind: str, effect_kind: str, **payload: object) -> CardLine:
    return CardLine(OracleInstruction(kind, "", dict(payload)), effect_kind)


CARD_LINE_INSTRUCTIONS: dict[str, dict[str, CardLine]] = {
    "Aladdin's Lamp": {
        "{x}, {t}: the next time you would draw a card this turn, instead look at "
        "the top x cards of your library, put all but one of them on the bottom of "
        "your library in a random order, then draw a card. x can't be 0":
            _line("arm_lamp_draw_replacement", "activated_draw"),
    },
    'Balance': {
        'each player chooses a number of lands they control equal to the number '
        'of lands controlled by the player who controls the fewest, then '
        'sacrifices the rest. players discard cards and sacrifice creatures the '
        'same way':
            _line('balance_resources', 'spell_pattern'),
    },
    'Berserk': {
        'target creature gains trample and gets +x/+0 until end of turn, where '
        'x is its power. at the beginning of the next end step, destroy that '
        'creature if it attacked this turn':
            _line('berserk_pump', 'spell_pattern'),
    },
    'Blaze of Glory': {
        'target creature defending player controls can block any number of '
        'creatures this turn. it blocks each attacking creature this turn if '
        'able':
            _line('grant_unlimited_blocking', 'spell_pattern'),
    },
    'Camouflage': {
        "this turn, instead of declaring blockers, each defending player chooses "
        "any number of creatures they control and divides them into a number of "
        "piles equal to the number of attacking creatures for whom that player is "
        "the defending player. creatures those players control that can block "
        "additional creatures may likewise be put into additional piles. assign "
        "each pile to a different one of those attacking creatures at random. each "
        "creature in a pile that can block the creature that pile is assigned to "
        "does so":
            _line("randomize_blockers", "spell_pattern"),
    },
    'Channel': {
        "until end of turn, any time you could activate a mana ability, you may "
        "pay 1 life. if you do, add {c}":
            _line("channel_life_for_mana", "spell_pattern"),
    },
    'Chaos Orb': {
        "{1}, {t}: if this artifact is on the battlefield, flip it onto the "
        "battlefield from a height of at least one foot. if this artifact turns "
        "over completely at least once during the flip, destroy all nontoken "
        "permanents it touches. then destroy this artifact":
            _line("chaos_orb_flip", "activated_chaos_orb"),
    },
    # Only the first of the two lines carries the instruction: the handler bans
    # the casting *and* sacrifices the permanents, so hooking the second line
    # too would put the same effect on the card twice.
    'City in a Bottle': {
        "whenever one or more other nontoken permanents with a name originally "
        "printed in the arabian nights expansion are on the battlefield, their "
        "controllers sacrifice them":
            _line("ban_and_sacrifice_set_permanents", "spell_pattern", set_code="arn"),
    },
    # "Put up to X +1/+0 counters on this creature" is templating the grammar
    # already parses; the sentence after it is not. The cap is what makes the
    # handler this card's — lowering the first sentence alone would let the
    # counters past seven.
    'Cyclone': {
        'at the beginning of your upkeep, put a wind counter on this '
        'enchantment, then sacrifice this enchantment unless you pay {g} for '
        'each wind counter on it. if you pay, this enchantment deals damage '
        'equal to the number of wind counters on it to each creature and each '
        'player':
            # {G} per wind counter is CR 702.24a's escalation printed longhand,
            # so it rides the same `per_counter` payload cumulative upkeep does
            # and `cumulative_upkeep.scaled_cost` is what reads it. The card
            # keeps a hook for the sentence *after* the payment — the damage
            # rider — which no other card shares.
            _line('upkeep_wind_counter_pay_or_sacrifice', 'upkeep_effect',
                mana={'G': 1}, per_counter='wind'),
    },
    'Cyclopean Tomb': {
        "{2}, {t}: put a mire counter on target non-swamp land. that land is a "
        "swamp for as long as it has a mire counter on it. activate only during "
        "your upkeep":
            _line("add_mire_counter_to_target_land", "activated_landtype"),
    },
    'Darkpact': {
        'you own target card in the ante. exchange that card with the top card '
        'of your library':
            _line('exchange_ante_with_top_library', 'spell_pattern'),
    },
    'Demonic Hordes': {
        "at the beginning of your upkeep, unless you pay {b}{b}{b}, tap this "
        "creature and sacrifice a land of an opponent's choice":
            _line(
                "upkeep_pay_or_tap_and_sacrifice_opponent_land", "upkeep_effect",
                mana={"W": 0, "U": 0, "B": 3, "R": 0, "G": 0, "C": 0, "generic": 0},
            ),
    },
    'Drain Power': {
        'target player activates a mana ability of each land they control. then '
        'that player loses all unspent mana and you add the mana lost this way':
            _line('drain_target_lands_mana', 'spell_pattern'),
    },
    'Drop of Honey': {
        "at the beginning of your upkeep, destroy the creature with the least "
        "power. it can't be regenerated. if two or more creatures are tied for "
        "least power, you choose one of them":
            _line("upkeep_destroy_least_power_creature", "upkeep_effect"),
    },
    'Earthbind': {
        'when this aura enters, if enchanted creature has flying, this aura '
        'deals 2 damage to that creature and this aura gains "enchanted '
        'creature loses flying."':
            _line('deal_damage', 'spell_pattern', amount=2),
    },
    'Erg Raiders': {
        "at the beginning of your end step, if this creature didn't attack this "
        "turn, it deals 2 damage to you unless it came under your control this turn":
            _line("end_step_damage_if_not_attacked", "triggered_damage", amount=2),
    },
    'Eye for an Eye': {
        "the next time a source of your choice would deal damage to you this turn, "
        "instead that source deals that much damage to you and eye for an eye "
        "deals that much damage to that source's controller":
            _line("arm_mirror_damage", "spell_pattern"),
    },
    'False Orders': {
        "remove target creature defending player controls from combat. creatures "
        "it was blocking that had become blocked by only that creature this combat "
        "become unblocked. you may have it block an attacking creature of your choice":
            _line("remove_creature_from_combat", "spell_pattern"),
    },
    # CR 104.1: the card asks a player to flip it onto a table, which this
    # engine cannot do. ``engine/dexterity.py`` substitutes a random landing
    # and explains why; the numbers here are the card's own reading of it —
    # one to three creatures. A hook because the four sentences are one card's
    # (Chaos Orb is the only other flip, and its effect is a different one),
    # while the *substitution* they share is not hooked at all.
    'Falling Star': {
        "flip falling star onto the playing area from a height of at least one "
        "foot. falling star deals 3 damage to each creature it lands on. tap all "
        "creatures dealt damage by falling star. if falling star doesn't turn "
        "completely over at least once during the flip, it has no effect":
            _line("deal_damage_to_random_creatures", "spell_pattern",
                amount=3, minimum=1, maximum=3, tap_damaged=True),
    },
    'Farmstead': {
        'enchanted land has "at the beginning of your upkeep, you may pay '
        '{w}{w}. if you do, you gain 1 life."':
            _line('target_gains_life', 'spell_pattern', amount=1,
                recipient='caster'),
    },
    'Forcefield': {
        "{1}: the next time an unblocked creature of your choice would deal combat "
        "damage to you this turn, prevent all but 1 of that damage":
            _line("grant_forcefield_shield", "activated_prevent"),
    },
    # `copy_top_stack_spell` copies the top of the stack rather than the named
    # target, and the two riders ("except that the copy is red", the optional
    # retarget) are the handler's own. All three are Fork's, not a shape.
    'Fork': {
        "copy target instant or sorcery spell, except that the copy is red. you "
        "may choose new targets for the copy":
            _line("copy_top_stack_spell", "spell_pattern"),
    },
    "Gaea's Liege": {
        '{t}: target land becomes a forest until this creature leaves the '
        'battlefield':
            _line('change_target_land_type', 'activated_landtype',
                land_type='forest'),
    },
    'Ghazbán Ogre': {
        "at the beginning of your upkeep, if a player has more life than each "
        "other player, the player with the most life gains control of this creature":
            _line("upkeep_most_life_gains_control", "upkeep_effect"),
    },
    # The first sentence is an ordinary numeric shield the grammar can read; the
    # rest of the line grants an activatable emblem, which is ON_SELF_RESOLVED
    # above. Claiming only the shield would drop the emblem silently, so the
    # whole line is one entry and the two halves stay in the same file.
    'Guardian Angel': {
        "prevent the next x damage that would be dealt to any target this turn. "
        "until end of turn, you may pay {1} any time you could cast an instant. if "
        "you do, prevent the next 1 damage that would be dealt to that permanent "
        "or player this turn":
            _line(
                "grant_prevention_shield", "spell_pattern",
                amount="x", to_self=False, to_source=False,
            ),
    },
    "Hurkyl's Recall": {
        'return all artifacts target player owns to their hand':
            _line('return_all_owned_artifacts_to_hand', 'spell_pattern'),
    },
    'Illusionary Mask': {
        '{x}: you may choose a creature card in your hand whose mana cost could '
        'be paid by some amount of, or all of, the mana you spent on {x}. if '
        'you do, you may cast that card face down as a 2/2 creature spell '
        'without paying its mana cost. if the creature that spell becomes as it '
        'resolves has not been turned face up and would assign or deal damage, '
        "be dealt damage, or become tapped, instead it's turned face up and "
        'assigns or deals damage, is dealt damage, or becomes tapped. activate '
        'only as a sorcery':
            _line('cast_face_down_creature', 'activated_cast'),
    },
    'Ivory Tower': {
        'at the beginning of your upkeep, you gain x life, where x is the '
        'number of cards in your hand minus 4':
            _line('upkeep_gain_life_over_hand_size', 'upkeep_effect', floor=4),
    },
    'Jade Monolith': {
        "{1}: the next time a source of your choice would deal damage to target "
        "creature this turn, that source deals that damage to you instead":
            _line("jade_monolith_redirect", "activated_prevent"),
    },
    'Jade Statue': {
        '{2}: this artifact becomes a 3/6 golem artifact creature until end of '
        'combat. activate only during combat':
            _line('animate_self_until_end_of_combat', 'activated_animate', power=3,
                toughness=6),
    },
    'Jeweled Bird': {
        "{t}: ante this artifact. if you do, put all other cards you own from the "
        "ante into your graveyard, then draw a card":
            _line("ante_self_then_clear_ante_and_draw", "activated_ante"),
    },
    # The whole card, as one line. Bespoke by the entry bar's own test: give an
    # invented card this text and it still needs a destroy whose subject is the
    # trigger's, plus an attach whose chooser is that subject's controller and
    # whose host is unchosen — three things the grammar reads separately and
    # none of which it composes yet. It was a dispatcher inside
    # ``tap_land_for_mana`` (``ENCHANTED_LAND_TAPPED_FOR_MANA``) until this
    # entry: as an instruction the line is announced by the tap seam, so it
    # fires however the land became tapped and goes on the stack like any other
    # trigger.
    'Kudzu': {
        "when enchanted land becomes tapped, destroy it. that land's controller "
        "may attach this aura to a land of their choice":
            _line("destroy_tapped_land_and_reoffer_aura", "triggered_destruction"),
    },
    'Mana Short': {
        'tap all lands target player controls and that player loses all unspent '
        'mana':
            _line('tap_target_player_lands_and_drain_mana', 'spell_pattern'),
    },
    # Mana bought with the mana value of the creature its additional cost ate.
    # The cost itself is not the hook's — it is the general CR 601.2b table
    # (engine/cast_costs.py), paid while casting — so the key is the *effect*
    # sentence alone. Sacrifice's plainer spelling ("an amount of {B} equal to
    # the sacrificed creature's mana value") is a production now and its entry
    # went with it; what keeps this one is the "1 plus" and the spend
    # restriction, which no second card prints together.
    'Metamorphosis': {
        "add x mana of any one color, where x is 1 plus the sacrificed creature's "
        "mana value. spend this mana only to cast creature spells":
            _line("sacrifice_creature_for_mana", "spell_pattern",
                color=None, bonus=1, spend_only="creature"),
    },
    'Mijae Djinn': {
        "whenever this creature attacks, flip a coin. if you lose the flip, remove "
        "this creature from combat and tap it":
            _line("coin_flip_remove_attacker_and_tap", "triggered_coin_flip"),
    },
    'Nafs Asp': {
        "whenever this creature deals damage to a player, that player loses 1 life "
        "at the beginning of their next draw step unless they pay {1} before that "
        "draw step":
            _line(
                "arm_draw_step_life_loss_unless_pay", "triggered_delayed_life_loss",
                amount=1, cost=1,
            ),
    },
    'Nether Shadow': {
        "at the beginning of your upkeep, if this card is in your graveyard with "
        "three or more creature cards above it, you may put this card onto the "
        "battlefield":
            _line(
                "upkeep_return_self_from_graveyard", "upkeep_effect",
                min_creatures_above=3,
            ),
    },
    # Aladdin's linked steal is a production (one condition, "for as long as you
    # control this"); this one is not. Its duration is two conditions, one of
    # them a comparison against the source's own power that is re-checked
    # continuously in game_ending.py — there is no second card to share it with.
    'Old Man of the Sea': {
        "{t}: gain control of target creature with power less than or equal to "
        "this creature's power for as long as this creature remains tapped and "
        "that creature's power remains less than or equal to this creature's power":
            _line("steal_creature_while_tapped_and_weaker", "activated_steal"),
    },
    'Oubliette': {
        'when this enchantment enters, target creature phases out until this '
        'enchantment leaves the battlefield. tap that creature as it phases in '
        'this way':
            _line('phase_out_target_creature_until_source_leaves', 'spell_pattern'),
    },
    'Personal Incarnation': {
        "{0}: the next 1 damage that would be dealt to this creature this turn is "
        "dealt to its owner instead. only this creatures owner may activate this "
        "ability":
            _line("redirect_one_damage_to_owner", "activated_prevent"),
        "when this creature dies, its owner loses half their life, rounded up":
            _line("owner_loses_half_life", "triggered_loss"),
    },
    # One bullet of a two-bullet modal activated ability. The destroy half used
    # to be hooked beside it, because "Aura attached to a land" was a
    # restriction the filter had no field for; ``attached_to_filter`` gave it one
    # (round 23, for Enchantment Alteration's "attached to a creature or land"),
    # so the production reads the line and the entry would be dead.
    'Pyramids': {
        "{2}: the next time target land would be destroyed this turn, remove all "
        "damage marked on it instead":
            _line("shield_target_land_from_destruction", "activated_prevent"),
    },
    'Raging River': {
        'whenever one or more creatures you control attack, each defending '
        'player divides all creatures without flying they control into a "left" '
        'pile and a "right" pile. then, for each attacking creature you '
        'control, choose "left" or "right." that creature can\'t be blocked this '
        'combat except by creatures with flying and creatures in a pile with '
        'the chosen label':
            _line('left_right_combat_division', 'triggered_combat'),
    },
    'Reverse Damage': {
        'the next time a source of your choice would deal damage to you this '
        'turn, prevent that damage. you gain life equal to the damage prevented '
        'this way':
            _line('grant_reverse_damage_shield', 'spell_pattern'),
    },
    'Reverse Polarity': {
        'you gain x life, where x is twice the damage dealt to you so far this '
        'turn by artifacts':
            _line('gain_twice_artifact_damage_taken', 'spell_pattern'),
    },
    "Ring of Ma'rûf": {
        "{5}, {t}, exile this artifact: the next time you would draw a card this "
        "turn, instead put a card you own from outside the game into your hand":
            _line("arm_outside_game_draw_replacement", "activated_draw"),
    },
    'Rohgahh of Kher Keep': {
        # The consequence names the card's own kobold tribe and hands the whole
        # pile to an opponent — no second card, real or plausibly printable,
        # shares the shape. The *name* it taps is payload, read through the same
        # subject filter every "named" phrase resolves by.
        # Keyed on the card's *full* name where the card prints the short one:
        # a legendary card's shortened self-reference is written out before any
        # line is classified (`engine/self_reference.py`), so this is the line
        # the compiler looks up.
        "at the beginning of your upkeep, you may pay {r}{r}{r}. if you don't, "
        'tap rohgahh of kher keep and all creatures named kobolds of kher keep, '
        'then an opponent gains control of them':
            _line(
                'upkeep_pay_or_cede_named_creatures', 'upkeep_effect',
                mana={"W": 0, "U": 0, "B": 0, "R": 3, "G": 0, "C": 0, "generic": 0},
                named='Kobolds of Kher Keep',
            ),
    },
    'Serendib Djinn': {
        "at the beginning of your upkeep, sacrifice a land. if you sacrifice an "
        "island this way, this creature deals 3 damage to you":
            _line(
                "upkeep_sacrifice_land_conditional_damage", "upkeep_effect",
                land_type="island", damage=3,
            ),
    },
    'Shahrazad': {
        "players play a magic subgame, using their libraries as their decks. each "
        "player who doesn't win the subgame loses half their life, rounded up":
            _line("opponents_lose_half_life", "spell_pattern"),
    },
    'Simulacrum': {
        'you gain life equal to the damage dealt to you this turn. simulacrum '
        'deals damage to target creature you control equal to the damage dealt '
        'to you this turn':
            _line('simulacrum_redirect', 'spell_pattern'),
    },
    'Sindbad': {
        "{t}: draw a card and reveal it. if it isn't a land card, discard it":
            _line('draw_reveal_discard_unless_land', 'activated_draw'),
    },
    "Siren's Call": {
        'creatures the active player controls attack this turn if able':
            _line('force_active_player_creatures_to_attack', 'spell_pattern'),
    },
    # **The one blocker swap Magic ever printed.** Three sentences that no
    # other card carries: two targets chosen with a relation *between* them, a
    # hypothetical about blocking legality asked of a block that has not
    # happened, and a reassignment of who blocks what. Written as an invented
    # card with the same text and no name, every clause of it would still be
    # unique — "could block all creatures that the other is blocking" appears on
    # this card and nowhere else in the game — so a production for it would be
    # a substring match in a grammar hat, claiming a sentence no second card
    # could ever share. The `targets` description is ordinary roles data
    # (engine/targeting.py), so the picker, the CR 602.2b gate and the CR 608.2b
    # re-check all read this entry rather than knowing the card.
    "Sorrow's Path": {
        "{t}: choose two target blocking creatures controlled by the same "
        "opponent. if each of those creatures could block all creatures that "
        "the other is blocking, remove both of them from combat. each one then "
        "blocks all creatures the other was blocking":
            _line(
                "swap_block_assignments", "activated_combat",
                targets={
                    "kind": "roles",
                    "roles": [
                        {
                            "role": "first",
                            "kind": "object",
                            "count": 1,
                            "filter": {
                                "type_filter": "creature",
                                "blocking_only": True,
                                "controller": "opponent",
                            },
                        },
                        {
                            "role": "second",
                            "kind": "object",
                            "count": 1,
                            "filter": {
                                "type_filter": "creature",
                                "blocking_only": True,
                                "controller": "opponent",
                            },
                            # "…controlled by **the same** opponent": which
                            # opponent is not a property of either creature, so
                            # it is a role dependency rather than a filter key.
                            "same_controller_role": "first",
                        },
                    ],
                },
            ),
    },
    'Stone Giant': {
        "{t}: target creature you control with toughness less than this creature's "
        "power gains flying until end of turn. destroy that creature at the "
        "beginning of the next end step":
            _line("grant_flying_and_delayed_destruction", "activated_keyword"),
    },
    'Timetwister': {
        'each player shuffles their hand and graveyard into their library, then '
        'draws seven cards':
            _line('timetwister', 'spell_pattern'),
    },
    'Wheel of Fortune': {
        'each player discards their hand, then draws seven cards':
            _line('wheel_of_fortune', 'spell_pattern'),
    },
    'Word of Command': {
        "look at target opponent's hand and choose a card from it. you control "
        'that player until word of command finishes resolving. the player plays '
        'that card if able. while doing so, the player can activate mana '
        "abilities only if they're from lands that player controls and only if "
        'mana they produce is spent to activate other mana abilities of lands '
        'the player controls and/or to play that card. if the chosen card is '
        'cast as a spell, you control the player while that spell is resolving':
            _line('peek_hand_and_force_play', 'spell_pattern'),
    },
    'Ydwen Efreet': {
        "whenever this creature blocks, flip a coin. if you lose the flip, remove "
        "this creature from combat and it can't block this turn. creatures it was "
        "blocking that had become blocked by only this creature this combat become "
        "unblocked":
            _line("coin_flip_remove_blocker", "triggered_coin_flip"),
    },
}


def card_line_instruction(card_name: str | None, normalized_line: str) -> CardLine | None:
    """The registered reading of *normalized_line* on the card named *card_name*.

    Both halves of the key matter. Keying on the text alone would make this a
    second `engine/parsing/` — a table any card could match by wording — and
    keying on the name alone would claim every line of the card, including the
    ones a production already reads.
    """
    if not card_name:
        return None
    return CARD_LINE_INSTRUCTIONS.get(card_name, {}).get(normalized_line)


def _guardian_angel(
    game: Game,
    caster: PlayerState,
    resolved_card: CardDefinition,
    target_player_index: int,
    target_permanent_index: int | None,
) -> None:
    # The first sentence (prevent the next X damage) resolves through the compiled
    # instruction. This hook adds the second sentence's granted ability: an emblem
    # the caster may activate ("pay {1}: prevent next 1 damage") until end of turn.
    # "That permanent or player" is the spell's original target, so the emblem
    # remembers it and never re-prompts on activation.
    caster.prevent_one_damage_emblems.append({
        "target_player_index": target_player_index,
        "target_permanent_index": target_permanent_index,
    })
    game.log.append(f"{caster.name} gains a Guardian Angel prevention emblem until end of turn")


ON_SELF_RESOLVED: dict[str, SelfResolvedHook] = {
    "Guardian Angel": _guardian_angel,
}


def _power_sink(game: Game, counter_card: CardDefinition, countered: StackItem) -> None:
    ctrl = game.players[countered.caster_index]
    for perm in game.controlled_by(countered.caster_index):
        if perm.card.primary_type == "land":
            game.become_tapped(perm)
    ctrl.mana_pool = {k: 0 for k in ctrl.mana_pool}
    game.log.append(f"{counter_card.name} tapped all lands and drained mana from {ctrl.name}")


ON_SPELL_COUNTERED: dict[str, SpellCounteredHook] = {
    "Power Sink": _power_sink,
}


def _cyclopean_tomb_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "When this artifact is put into a graveyard from the battlefield, at the
    # beginning of each of your upkeeps for the rest of the game, remove all mire
    # counters from a land that a mire counter was put onto with this artifact but
    # that a mire counter has not been removed from with this artifact."
    #
    # Set up a rest-of-game obligation that removes the mire counter from one such
    # land per upkeep (drained in Game.resolve_upkeep). Only lands that are still
    # mired qualify — any whose counter was already removed are excluded.
    mired = permanent.metadata.get("mired_lands") or []
    remaining = [land for land in mired if land.metadata.get("mire_counter")]
    if not remaining:
        return
    controller_index = game.players.index(owner)
    game.mire_cleanup_obligations.append(
        {"controller_index": controller_index, "lands": remaining}
    )
    game.log.append(
        f"{permanent.card.name} left the battlefield; "
        f"{len(remaining)} mired land(s) will be freed over future upkeeps"
    )


def _consecrate_land_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "Enchanted land has indestructible and can't be enchanted by other Auras."
    # Both are continuous effects from this Aura — when it leaves the battlefield
    # the enchanted land loses indestructibility and may again be enchanted.
    land = permanent.metadata.get("attached_to")
    if land is None:
        return
    land.metadata.pop("is_indestructible", None)
    land.metadata.pop("cant_be_enchanted_by_auras", None)
    detach_aura(permanent, land)


def _gaeas_liege_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "{T}: Target land becomes a Forest until this creature leaves the
    # battlefield." When Gaea's Liege leaves, the lands it forested revert to
    # their printed type (CR 611.3 — the duration ends).
    # Dropping this creature's own contribution, not clearing the land's type:
    # the land goes back to whatever the *remaining* effects say it is, which is
    # what "the duration ended" means. Reading the stored type back to check it
    # was still Forest was the bookkeeping this replaces — and it was wrong
    # whenever something newer had made the land something else, since the
    # Liege's effect would then have gone on applying invisibly.
    reverted = 0
    for land in permanent.metadata.get("forested_lands", []) or []:
        if end_land_type_change(land, source=permanent):
            reverted += 1
    if reverted:
        game.log.append(
            f"{permanent.card.name} left the battlefield; {reverted} land(s) reverted from Forest"
        )
    game._refresh_dynamic_creatures()


def _revert_linked_steal_on_leave(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # A linked-duration "gain control for as long as you control this" steal
    # (Aladdin's artifact, Old Man of the Sea's creature) ends when its source
    # leaves the battlefield (CR 611.3), mirroring how Control Magic / Steal
    # Artifact revert when their Aura leaves. Old Man's other end conditions
    # (untaps / stolen power exceeds its own) are swept continuously in
    # game_ending.py.
    game.end_control_changes_from(permanent)


def _oubliette_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "Target creature phases out until this enchantment leaves the
    # battlefield. Tap that creature as it phases in this way." Scoped
    # exile-and-return (not full CR 702.26 phasing) tracked on Oubliette
    # itself — the phased creature and any Auras/Equipment that phased out
    # with it return, tapped, when Oubliette leaves.
    phased = permanent.metadata.pop("phased_out_permanent", None)
    owner_index = permanent.metadata.pop("phased_out_owner_index", None)
    attachments = permanent.metadata.pop("phased_out_attachments", None) or []
    # CR 400.7: this is the one path that puts the *same* ``Permanent`` object
    # back on the battlefield, so the new-object rule has to be applied by hand
    # — anything still holding the pre-phase-out id must not resolve to it.
    if phased is not None and isinstance(owner_index, int) and 0 <= owner_index < len(game.players):
        phased.tapped = True
        phased.permanent_id = next_permanent_id()
        game.players[owner_index].battlefield.append(phased)
        game.log.append(
            f"{phased.card.name} phases back in, tapped ({permanent.card.name} left the battlefield)"
        )
    for seat, attached_perm in attachments:
        if 0 <= seat < len(game.players):
            attached_perm.permanent_id = next_permanent_id()
            game.players[seat].battlefield.append(attached_perm)


ON_LEAVE_BATTLEFIELD: dict[str, LeaveBattlefieldHook] = {
    "Cyclopean Tomb": _cyclopean_tomb_leaves,
    "Consecrate Land": _consecrate_land_leaves,
    "Gaea's Liege": _gaeas_liege_leaves,
    "Aladdin": _revert_linked_steal_on_leave,
    "Old Man of the Sea": _revert_linked_steal_on_leave,
    "Oubliette": _oubliette_leaves,
}


# --------------------------------------------------------------------------
# Resolve-time trigger hooks
# --------------------------------------------------------------------------
# A triggered ability whose effect is a name-keyed hook is put on the stack like
# any other trigger. When it resolves, resolve_top_of_stack dispatches to
# TRIGGER_HOOKS[stack_item.hook_key], passing the StackItem; the handler reads
# stack_item.hook_event (captured when the trigger fired) and runs the effect.
# This is how the Rod/Cup/Sphere cycle and Verduran Enchantress raise their
# "you may pay {1} / draw a card" prompts at resolution rather than at fire time.

TriggerStackHook = Callable[["Game", "StackItem"], None]


def _resolve_optional_pay_trigger(game: Game, item: StackItem) -> None:
    """Resolve a deferred "you may pay {N}: gain life" / "you may draw a card"
    trigger (the color Rods, Verduran Enchantress). The pay/draw prompt is registered
    here — at resolution — so it appears only after the trigger leaves the stack,
    matching the Soul Net death-trigger behavior. A paid rider (Rods) is offered only
    when the controller can actually pay the {N}; a free rider (Verduran's draw) is
    always offered."""
    ev = item.hook_event or {}
    player_index = ev.get("player_index")
    if player_index is None or not (0 <= player_index < len(game.players)):
        return
    cost = generic_cost(int(ev.get("cost", 0)))
    entry: dict = {
        "card_name": ev["card_name"],
        "cost": cost,
        "life": int(ev.get("life", 0)),
    }
    if total_pips(cost) > 0 and not game._player_can_pay_optional(
        game.players[player_index], entry
    ):
        return
    if "draw" in ev:
        entry["draw"] = ev["draw"]
    if "prompt" in ev:
        entry["prompt"] = ev["prompt"]
    game.arm_pending_choice("optional_pay", player_index, **entry)


# hook_key → resolver.
TRIGGER_HOOKS: dict[str, TriggerStackHook] = {
    "optional_pay": _resolve_optional_pay_trigger,
}


# --------------------------------------------------------------------------
# Untap-step restrictions (CR 502) — moved out
# --------------------------------------------------------------------------
# Stasis, Winter Orb, Smoke, Meekstone and Magnetic Mountain used to be five
# name-keyed UntapRestriction entries here. Their wordings are templates, so
# the restriction is now derived from oracle text in
# engine/untap_restrictions.py and a card printed with one of those templates
# needs no registration at all.


# --------------------------------------------------------------------------
# Untapped artifact protectors
# --------------------------------------------------------------------------
# Guardian Beast: "As long as this creature is untapped, noncreature artifacts
# you control can't be enchanted, have indestructible, and other players
# can't gain control of them." Checked by
# effects.py:_untapped_artifact_protector_active at each relevant site
# (destroy, enchant-target legality, control-change legality) rather than
# precomputed, since the protection tracks the source's tapped state.

UNTAPPED_ARTIFACT_PROTECTORS: frozenset[str] = frozenset({"Guardian Beast"})


# --------------------------------------------------------------------------
# Top-of-library discard replacements — moved out
# --------------------------------------------------------------------------
# Library of Leng was a name-keyed frozenset here. It is now a text-keyed
# `discard` replacement in engine/replacements.py, offering the optional
# destination as a ReplacementChoice.


# --------------------------------------------------------------------------
# Draw-step modifiers (CR 504)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DrawStepModifier:
    """Draw-step behavior granted by a permanent.

    optional_skip_grants_protection -- its controller may skip their draw to
                  gain "attack only me with flyers" protection (Island Sanctuary)
    """

    optional_skip_grants_protection: bool = False


# Howling Mine's "that player draws an additional card" moved out to
# engine/draw_step_modifiers.py: it is a template a long line of cards
# reprints, so it is derived from oracle text instead of registered here.
# Island Sanctuary stays because the quality it grants protection against
# ("creatures with flying and/or islandwalk") is specific to the card — until
# a second card grants a different quality there is nothing to generalize.
DRAW_STEP_MODIFIERS: dict[str, DrawStepModifier] = {
    "Island Sanctuary": DrawStepModifier(optional_skip_grants_protection=True),
}


# --------------------------------------------------------------------------
# Land-tapping triggers — moved out
# --------------------------------------------------------------------------
# Mana Flare, Gauntlet of Might and Lifetap were three name-keyed entries here,
# across two registries (MANA_PRODUCTION_MODIFIERS and ON_BECOMES_TAPPED). All
# three are templates the compiler now reads:
#
#   "Whenever a <type> [an opponent controls] becomes tapped, …" compiles to a
#   `permanent_becomes_tapped` condition carrying the type and the controller
#   scope as payload, dispatched by engine/events.py.
#   "Whenever a [<land type>] is tapped for mana, <player> adds …" compiles to
#   `land_tapped_for_mana` plus an `add_mana_for_tapped_land` instruction,
#   resolved inline by Game.tap_land_for_mana (CR 605.4a — a triggered mana
#   ability never uses the stack).
#
# A card printed with either template needs no registration at all.


# --------------------------------------------------------------------------
# Enchanted-land "when tapped for mana" bespoke effects
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Cost modifiers — moved out
# --------------------------------------------------------------------------
# Gloom was two hand-written functions keyed by name. "<colour> spells cost
# {N} more to cast" is a template Magic reprints constantly, so the tax is
# now derived from oracle text in engine/cost_modifiers.py.

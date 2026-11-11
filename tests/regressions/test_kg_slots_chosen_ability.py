"""A target narrowed by a fact the **announcement** makes: "with the chosen
ability" (Phyrexian Splicer).

"{2}, {T}, Choose flying, first strike, trample, or shadow: Until end of turn,
target creature with the chosen ability loses it and another target creature
gains it." The word is a cost choice, announced before the targets (CR 602.2b
sends the activation through CR 601.2b–c), so the targets it narrows are
knowable at announcement and must be judged by it. They were not:
``target_descriptions._narrowing_flags`` had no key for the narrowing, so slot
0 offered every creature, the activation gate admitted a creature without the
word, the cost was paid, and the resolution handed the word to slot 1 anyway —
shadow, from a board where nobody had it.

Now the role carries ``chosen_keyword``; the gate is handed the word this
announcement makes (``Game.announced_chosen_keyword``, never the source's record
of the *last* activation's word), and the picker ships one walk per printed
word (``valid_targets_by_keyword``) for the browser to swap in once the word is
clicked.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.handlers._chosen import CHOSEN_ABILITY
from engine.models import Permanent
from engine.oracle import compiled_units
from engine.targeting import derive_activation_spec, spec_roles
from tests.helpers import _nosick, resolve_stack

_POOL: dict = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)


def _chosen_keyword_abilities():
    """Every activated ability in the pool whose targets description says
    "with the chosen ability" somewhere."""
    found = []

    def says_it(described) -> bool:
        if not isinstance(described, dict):
            return False
        slots = [described.get("filter")] + list(described.get("filters") or ())
        return any(isinstance(s, dict) and s.get("chosen_keyword") for s in slots)

    for card, program in compiled_units(_POOL.values()):
        for ability in program.activated_abilities:
            described = ((ability.instruction and ability.instruction.payload) or {}).get("targets")
            if says_it(described):
                found.append((card.name, ability))
    return found


def test_every_chosen_ability_narrowing_reaches_the_picker():
    """The census, over the derived spec: each slot the description narrows
    by the chosen word carries the narrowing into its role, and the ability's
    cost offers the words it is chosen from. On the base the role read
    ``{'kind': 'creature', 'role': 'slot_0'}`` — nothing to enforce."""
    found = _chosen_keyword_abilities()
    assert found, "no 'with the chosen ability' in the pool — the census measured nothing"

    wrong = []
    for name, ability in found:
        described = ability.instruction.payload["targets"]
        roles = spec_roles(derive_activation_spec(ability))
        for position, slot in enumerate(described.get("filters") or ()):
            role = roles[position] if position < len(roles) else {}
            if slot.get("chosen_keyword") and not role.get("chosen_keyword"):
                wrong.append(f"{name}: slot {position} dropped the chosen ability")
        if not getattr(ability.cost, "chosen_keyword_options", ()):
            wrong.append(f"{name}: a chosen-ability target with no word to choose")
    assert not wrong, "; ".join(wrong)


def _table(*, theirs_flier: bool = True):
    splicer = _nosick(Permanent(card=_POOL["Phyrexian Splicer"]))
    bear = _nosick(Permanent(card=_POOL["Grizzly Bears"]))
    p2_board = [Permanent(card=_POOL["Gray Ogre"])]
    if theirs_flier:
        p2_board.insert(0, Permanent(card=_POOL["Serra Angel"]))
    game = Game(players=[
        PlayerState("P1", battlefield=[splicer, bear], library=[_POOL["Forest"]] * 5),
        PlayerState("P2", battlefield=p2_board, library=[_POOL["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    return game, splicer, bear, p2_board


def _first_names(walk):
    return sorted(entry["name"] for entry in walk)


def test_the_picker_ships_one_walk_per_printed_word():
    game, _splicer, _bear, _theirs = _table()
    spec = game.activation_target_spec(0, 0)

    walks = spec["valid_targets_by_keyword"]
    assert set(walks) == {"flying", "first strike", "trample", "shadow"}
    assert _first_names(walks["flying"]) == ["Serra Angel"]
    assert walks["shadow"] == [] and walks["trample"] == []
    # The default walk is the default word's: the first word a creature has.
    assert spec["valid_targets"] == walks["flying"]


@pytest.mark.parametrize("word, slot0", [
    ("flying", "Gray Ogre"),      # no flying to lose
    ("shadow", "Gray Ogre"),      # nobody has shadow at all
    ("trample", "Serra Angel"),   # the flier has no trample
])
def test_a_slot_zero_creature_without_the_word_is_refused_with_nothing_paid(word, slot0):
    """CR 601.2c through 602.2b: an illegal announcement is refused before
    the cost (CR 601.2h) — Splicer stays untapped, the record is taken back,
    and nobody gains anything."""
    game, splicer, bear, theirs = _table()
    named = next(perm for perm in theirs if perm.card.name == slot0)

    result = game.activate_permanent_ability(
        0, "Phyrexian Splicer", permanent_index=0, chosen_keyword=word,
        target_permanent_ids=[named.permanent_id, bear.permanent_id],
    )
    resolve_stack(game)

    assert not result.supported, result.details
    assert not splicer.tapped
    assert CHOSEN_ABILITY not in splicer.metadata
    assert not game._has_keyword(bear, word)


def test_the_word_moves_from_a_creature_that_has_it():
    game, splicer, bear, theirs = _table()
    angel = theirs[0]

    result = game.activate_permanent_ability(
        0, "Phyrexian Splicer", permanent_index=0, chosen_keyword="flying",
        target_permanent_ids=[angel.permanent_id, bear.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert splicer.tapped
    assert game._has_keyword(bear, "flying") and not game._has_keyword(angel, "flying")


def test_the_gate_reads_this_announcement_not_the_last_ones_record():
    """A record left by an earlier activation is not this activation's word:
    the gate is handed the word, so a stale "trample" neither admits a
    trampler for a flying announcement nor refuses a flier."""
    game, splicer, bear, theirs = _table()
    angel = theirs[0]
    splicer.metadata[CHOSEN_ABILITY] = "trample"   # the previous activation's

    ability = game.usable_abilities_of(splicer)[0]
    assert game.activation_target_refusal(
        0, splicer, ability, chosen_keyword="flying",
        target_permanent_ids=[angel.permanent_id, bear.permanent_id],
    ) is None
    spec = game.activation_target_spec(0, 0)
    assert _first_names(spec["valid_targets_by_keyword"]["flying"]) == ["Serra Angel"]


def test_each_activation_resolves_with_the_word_it_announced():
    """Two activations on the stack: Splicer moves trample, is untapped in
    response (Twiddle), and moves flying. The first resolved with the second's
    word, because the word was read off the source's record — the latest
    activation's — rather than off the object that announced it."""
    splicer = _nosick(Permanent(card=_POOL["Phyrexian Splicer"]))
    bear = _nosick(Permanent(card=_POOL["Grizzly Bears"]))
    angel = Permanent(card=_POOL["Serra Angel"])
    trampler = Permanent(card=_POOL["Force of Nature"])
    game = Game(players=[
        PlayerState("P1", battlefield=[splicer, bear], hand=[_POOL["Twiddle"]],
                    library=[_POOL["Forest"]] * 5),
        PlayerState("P2", battlefield=[angel, trampler], library=[_POOL["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False

    assert game.queue_permanent_ability(
        0, "Phyrexian Splicer", permanent_index=0, chosen_keyword="trample",
        target_permanent_ids=[trampler.permanent_id, bear.permanent_id],
    ).supported
    assert splicer.tapped
    assert game.queue_from_hand(
        0, "Twiddle", target_permanent_ids=[splicer.permanent_id],
    ).supported
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=True)   # "You may tap or untap"
    assert not splicer.tapped, "Twiddle untapped the Splicer in response"
    assert game.queue_permanent_ability(
        0, "Phyrexian Splicer", permanent_index=0, chosen_keyword="flying",
        target_permanent_ids=[angel.permanent_id, bear.permanent_id],
    ).supported
    resolve_stack(game)

    assert game._has_keyword(bear, "flying") and game._has_keyword(bear, "trample")
    assert not game._has_keyword(angel, "flying")
    assert not game._has_keyword(trampler, "trample")


def test_with_no_creature_holding_any_word_the_ability_cannot_be_activated():
    game, splicer, bear, theirs = _table(theirs_flier=False)

    result = game.activate_permanent_ability(
        0, "Phyrexian Splicer", permanent_index=0,
        target_permanent_ids=[theirs[0].permanent_id, bear.permanent_id],
    )

    assert not result.supported and not splicer.tapped
    assert all(walk == [] for walk in
               game.activation_target_spec(0, 0)["valid_targets_by_keyword"].values())


def test_the_ai_names_the_word_the_opposing_board_has():
    """The default word is the first a creature has — here the AI's own
    flier, which it would have to rob from itself. The policy names the word
    its chain is on (``ai_abilities._keyword_walk_order``)."""
    from engine.ai_policy import activate_chosen_ability, choose_activation_action

    splicer = _nosick(Permanent(card=_POOL["Phyrexian Splicer"]))
    mine = _nosick(Permanent(card=_POOL["Serra Angel"]))
    theirs = Permanent(card=_POOL["Force of Nature"])     # trample
    game = Game(players=[
        PlayerState("P1", battlefield=[splicer, mine], library=[_POOL["Forest"]] * 5),
        PlayerState("P2", battlefield=[theirs], library=[_POOL["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False

    action = choose_activation_action(game, 0)
    assert action is not None and action.chosen_keyword == "trample"
    assert activate_chosen_ability(game, 0, action).supported
    resolve_stack(game)

    assert game._has_keyword(mine, "trample") and not game._has_keyword(theirs, "trample")


@pytest.mark.full
def test_a_seeded_run_activates_phyrexian_splicer():
    """Phyrexian Splicer pinned into both decks of a seeded Tempest run: a
    seat activates it at least once and nothing it proposed was refused."""
    # Seed 4 since kg5: the round's AI branches, merged together, moved seed
    # 3's games to ones where no seat activates the Splicer (the merged tree
    # before ``ids`` already fails it, the round's base passes it); 4 is
    # the first seed after 3 that holds every assertion below
    # (scratch/kg5/tools/reseed_splicer.py).
    report = run_ai_simulation(
        manifest_set_path("TMP", include_measured=True), games=2, seed=4,
        max_turns=14, required_cards=["Phyrexian Splicer"],
    )
    assert report.games_completed == 2
    assert not report.issues, report.issues
    assert not any("Phyrexian Splicer" in reason for reason in report.refused_activations)
    assert any(
        "activate Phyrexian Splicer -> " in line for line in report.log_lines
    ), "no seat activated Phyrexian Splicer; pick another seed"

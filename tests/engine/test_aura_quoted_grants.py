"""Every ability an Aura grants in quotes has to be one the compiler reads.

``engine/auras.py`` claims ``<attached> <noun> has "<anything>"`` as an
implemented continuous effect, and the claim asks nothing of the quote: the
words are folded onto the host by ``Permanent.effective_card`` and the host's
own compile is what turns them into an ability — or does not. So an Aura whose
quote the grammar refuses is reported **supported**, attaches, and grants a
sentence no step ever acts on. No instrument sees it: the Aura's program is
clean, ``--hollow-lines`` reads parts and the Aura has none, ``parse_coverage``
takes the claim at its word, and the unreadable line is on a *different
permanent* from the card that printed it.

Invasion's Essence Leak found it, by printing the same quote Urza's Saga's
Pendrell Flux had shipped with for nine sets — "At the beginning of your upkeep,
sacrifice this creature unless you pay its mana cost." — which refused in the
parser asking for a "reduced by" the card never prints. Pendrell Flux was an
Aura that did nothing at all.

This is the census that would have said so. It is validated backwards: on the
tree before that fix it names Pendrell Flux as well as the card below.
"""

from __future__ import annotations

from engine.faces import compilation_units
from engine.auras import aura_granted_ability_lines
from engine.card_loader import load_cards, manifest_set_paths
from engine.granted_abilities import granted_ability_supported
from engine.oracle import compile_card_oracle

#: Supported Auras whose quoted grant the compiler cannot read **today**, with
#: what is missing. A ratchet in both directions: a name appearing here that
#: the census no longer finds fails as stale, and a new one fails as a defect.
#:
#: Archery Training (Urza's Destiny): 'Enchanted creature has "{T}: This
#: creature deals X damage to target attacking or blocking creature, where X is
#: the number of arrow counters on Archery Training."' The quote names the
#: *Aura* from inside an ability the *host* has. Folded onto the host it is a
#: proper noun the grammar has never heard of, and nothing binds it back to the
#: attachment — so the host gets no ability and the arrow counters the Aura's
#: own upkeep line accumulates are read by nothing.
KNOWN_UNREAD: frozenset[str] = frozenset({"Archery Training"})

#: How many quoted grants the pool held when this was written. A floor, because
#: a census that examined nothing passes for the same reason as one that found
#: nothing.
EXAMINED_FLOOR = 20


def _census() -> tuple[int, set[str]]:
    """``(grants examined, supported Auras with a quote the compiler refuses)``.

    Both manifest roles: a measured set is exactly where the next printing of
    an already-shipped quote arrives, which is how this one was found.
    """
    examined = 0
    unread: set[str] = set()
    seen: set[str] = set()
    for path in manifest_set_paths(include_measured=True):
        for card in compilation_units(load_cards(path)):
            # A half shares its card's oracle_id, so the name is the key.
            key = card.name
            if key in seen:
                continue
            seen.add(key)
            for line in aura_granted_ability_lines(card.oracle_text or ""):
                examined += 1
                if not compile_card_oracle(card).supported:
                    continue
                if not granted_ability_supported(line):
                    unread.add(card.name)
    return examined, unread


def test_every_supported_auras_quoted_grant_compiles_on_its_host():
    examined, unread = _census()
    assert examined >= EXAMINED_FLOOR, (
        f"the census examined {examined} quoted grants; it found "
        f"{EXAMINED_FLOOR} when written, so the reader it is built on moved"
    )
    new = sorted(unread - KNOWN_UNREAD)
    assert not new, (
        "these Auras report supported and grant a quoted ability the compiler "
        f"cannot read, so the host gains nothing: {new}"
    )
    stale = sorted(KNOWN_UNREAD - unread)
    assert not stale, (
        f"KNOWN_UNREAD names Auras whose quote now compiles: {stale} — remove "
        "them so the next regression is not pre-excused"
    )


def test_the_census_reads_a_quote_the_way_the_host_will():
    """The probe is the question the game asks — one printed sentence compiled
    on a card that says nothing else — so it must answer yes for a quote a host
    demonstrably runs and no for one it demonstrably cannot.
    """
    assert granted_ability_supported(
        "At the beginning of your upkeep, sacrifice this creature unless you "
        "pay its mana cost."
    )
    assert granted_ability_supported(
        "At the beginning of your upkeep, sacrifice this creature unless you "
        "pay {2}."
    )
    assert not granted_ability_supported(
        "{T}: This creature deals X damage to target attacking or blocking "
        "creature, where X is the number of arrow counters on Archery Training."
    )

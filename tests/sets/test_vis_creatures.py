"""Visions creatures.

Opened at the set's ingest with the yield of Phase 1's suite run — see
SET_PLAYBOOK.md, "treat what fires as yield, not noise".
"""

from engine.oracle import compile_card_oracle


def test_kyscu_drake_charges_both_halves_of_its_conjoined_sacrifice(set_pool):
    """"Sacrifice this creature **and a creature named Spitting Drake**".

    Two objects under one printed verb, joined by a bare "and" with no comma —
    the shape every reader in the charger declined. The Oxford-list regex needs
    a comma before its "and", the single-object delimiter is switched off once
    "sacrifice this ..." has set ``sacrifice_self``, and the "any number of"
    reader wants a set. So the Drake's own sacrifice was charged and the second
    creature was not: an ability activated for less than the card prints, which
    is the failure that neither crashes nor goes missing.
    """
    drake = set_pool("VIS")["Kyscu Drake"]
    program = compile_card_oracle(drake)

    tutor = [
        ability
        for ability in program.activated_abilities
        if ability.cost.sacrifice_self
    ]
    assert len(tutor) == 1, "the tutor ability is the one that sacrifices itself"
    cost = tutor[0].cost

    # The source in its flag and the chosen permanent in the filter — the same
    # encoding the Oxford-list path already gives the same two facts.
    assert cost.sacrifice_self is True
    assert cost.sacrifice_filter == {
        "type_filter": "creature",
        "named": "spitting drake",
    }

"""Compatibilité ABO/Rh pour un don de sang total (RG4). Même logique que BloodCompatibility.cs côté MAUI."""

from app.enums import BloodGroup, Rhesus


def _abo_compatible(donor: BloodGroup, recipient: BloodGroup) -> bool:
    if donor == BloodGroup.O:
        return True
    if donor == BloodGroup.A:
        return recipient in (BloodGroup.A, BloodGroup.AB)
    if donor == BloodGroup.B:
        return recipient in (BloodGroup.B, BloodGroup.AB)
    return recipient == BloodGroup.AB  # donneur AB


def _rhesus_compatible(donor: Rhesus, recipient: Rhesus) -> bool:
    # Un donneur Rh négatif peut donner à tous ; un donneur Rh positif seulement à un receveur Rh positif.
    return donor == Rhesus.NEGATIVE or recipient == Rhesus.POSITIVE


def can_donate(
    donor_group: BloodGroup, donor_rhesus: Rhesus, recipient_group: BloodGroup, recipient_rhesus: Rhesus
) -> bool:
    return _abo_compatible(donor_group, recipient_group) and _rhesus_compatible(donor_rhesus, recipient_rhesus)


def compatible_donor_types(recipient_group: BloodGroup, recipient_rhesus: Rhesus) -> list[tuple[BloodGroup, Rhesus]]:
    return [
        (group, rhesus)
        for group in BloodGroup
        for rhesus in Rhesus
        if can_donate(group, rhesus, recipient_group, recipient_rhesus)
    ]


def format_group(group: BloodGroup, rhesus: Rhesus) -> str:
    return f"{group.value}{'+' if rhesus == Rhesus.POSITIVE else '-'}"

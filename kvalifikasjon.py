"""Felles kvalifikasjonsnivåer for ansatte og oppdrag."""

from enum import IntEnum


class Kvalifikasjonsniva(IntEnum):
    """De to kvalifikasjonsnivåene som prototypen bruker."""

    UTEN_HELSEFAGLIG_UTDANNING = 0
    KVALIFISERT = 1

    @property
    def visningsnavn(self) -> str:
        """Returner en lesbar tekst til utskriften."""

        if self is Kvalifikasjonsniva.KVALIFISERT:
            return "Kvalifisert helsepersonell"
        return "Uten helsefaglig utdanning"

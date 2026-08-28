"""Datamodell for et oppdrag i hjemmetjenesten."""

from dataclasses import dataclass
from typing import Optional

from besoksrunde import Besoksrunde
from kvalifikasjon import Kvalifikasjonsniva


@dataclass(frozen=True)
class Oppdrag:
    """Informasjon vi trenger om ett oppdrag i den første prototypen.

    Klassen er uforanderlig (``frozen=True``), fordi et oppdrag ikke skal
    endres mens algoritmen planlegger ruten.
    """

    id: str
    navn: str
    adresse: str
    varighet: int  # Forventet tid hos brukeren, målt i minutter.
    lengdegrad: float
    breddegrad: float
    minimum_kvalifikasjon: Kvalifikasjonsniva
    besoksrunde: Besoksrunde
    # Disse brukes bare når en bruker har et absolutt, individuelt tidskrav.
    kritisk_tidligste_start: Optional[int] = None
    kritisk_seneste_start: Optional[int] = None
    antall_ansatte: int = 1

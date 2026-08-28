"""Definisjon av de fire besøksrundene i løpet av dagen."""

from enum import Enum


class Besoksrunde(Enum):
    """Navn og ønsket tidsrom for én besøksrunde."""

    DAG = ("Dag", 8 * 60 + 30, 12 * 60)
    LUNSJ = ("Lunsj", 13 * 60, 14 * 60)
    MIDDAG = ("Middag", 15 * 60, 18 * 60)
    KVELD = ("Kveld", 19 * 60, 22 * 60)

    def __init__(self, visningsnavn: str, starttid: int, sluttid: int):
        self.visningsnavn = visningsnavn
        self.starttid = starttid
        self.sluttid = sluttid

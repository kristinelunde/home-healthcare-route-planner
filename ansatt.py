"""Datamodeller for ansatte og rutene deres."""

from dataclasses import dataclass, field

from kvalifikasjon import Kvalifikasjonsniva
from oppdrag import Oppdrag


@dataclass(frozen=True)
class Ansatt:
    """En ansatt som kan få tildelt oppdrag."""

    id: str
    navn: str
    kvalifikasjon: Kvalifikasjonsniva


@dataclass
class AnsattRute:
    """Ruten og de løpende summene for én ansatt."""

    ansatt: Ansatt
    stopp: list[tuple[Oppdrag, int]] = field(default_factory=list)
    tidspunkter: list[tuple[int, int]] = field(default_factory=list)
    navarende_sted: str = "Depot"
    kjoretid_til_depot: int = 0
    tilbake_pa_depot_tid: int = 0
    total_kjoretid: int = 0
    total_arbeidstid: int = 0

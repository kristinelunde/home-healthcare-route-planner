"""Startpunkt for prototypen av ruteplanleggeren."""

import os

from ansatt import Ansatt, AnsattRute
from besoksrunde import Besoksrunde
from kvalifikasjon import Kvalifikasjonsniva
from openrouteservice import hent_kjoretidsmatrise
from oppdrag import Oppdrag
from ruteplanlegger import planlegg_ruter


# Koordinatene skrives som (lengdegrad, breddegrad), slik API-et forventer.
DEPOT_KOORDINATER = (10.7606, 59.9184)


def lag_testoppdrag_per_runde() -> dict[Besoksrunde, list[Oppdrag]]:
    """Lag separate eksempeloppdrag for hver besøksrunde."""

    alle = Kvalifikasjonsniva.UTEN_HELSEFAGLIG_UTDANNING
    kvalifisert = Kvalifikasjonsniva.KVALIFISERT

    return {
        Besoksrunde.DAG: [
            Oppdrag(
                "D1", "Bruker A", "Karl Johans gate 1, Oslo", 30,
                10.7506, 59.9111, kvalifisert, Besoksrunde.DAG,
                9 * 60, 10 * 60,
            ),
            Oppdrag(
                "D2", "Bruker B", "Kirkeveien 166, Oslo", 20,
                10.7346, 59.9367, alle, Besoksrunde.DAG,
            ),
            Oppdrag(
                "D3", "Bruker C", "Sognsveien 75 A, Oslo", 45,
                10.7342, 59.9489, kvalifisert, Besoksrunde.DAG,
            ),
            Oppdrag(
                "D4", "Bruker D", "Bogstadveien 30, Oslo", 25,
                10.7180, 59.9252, kvalifisert, Besoksrunde.DAG,
                antall_ansatte=2,
            ),
            Oppdrag(
                "D5", "Bruker E", "Trondheimsveien 100, Oslo", 35,
                10.7798, 59.9281, alle, Besoksrunde.DAG,
            ),
        ],
        Besoksrunde.LUNSJ: [
            Oppdrag(
                "L1", "Bruker F", "Karl Johans gate 1, Oslo", 25,
                10.7506, 59.9111, kvalifisert, Besoksrunde.LUNSJ,
                13 * 60 + 10, 13 * 60 + 40,
            ),
            Oppdrag(
                "L2", "Bruker G", "Kirkeveien 166, Oslo", 20,
                10.7346, 59.9367, alle, Besoksrunde.LUNSJ,
            ),
            Oppdrag(
                "L3", "Bruker H", "Bogstadveien 30, Oslo", 30,
                10.7180, 59.9252, alle, Besoksrunde.LUNSJ,
            ),
        ],
        Besoksrunde.MIDDAG: [
            Oppdrag(
                "M1", "Bruker I", "Sognsveien 75 A, Oslo", 35,
                10.7342, 59.9489, kvalifisert, Besoksrunde.MIDDAG,
            ),
            Oppdrag(
                "M2", "Bruker J", "Bogstadveien 30, Oslo", 25,
                10.7180, 59.9252, alle, Besoksrunde.MIDDAG,
                antall_ansatte=2,
            ),
            Oppdrag(
                "M3", "Bruker K", "Trondheimsveien 100, Oslo", 30,
                10.7798, 59.9281, alle, Besoksrunde.MIDDAG,
            ),
        ],
        Besoksrunde.KVELD: [
            Oppdrag(
                "K1", "Bruker L", "Karl Johans gate 1, Oslo", 30,
                10.7506, 59.9111, kvalifisert, Besoksrunde.KVELD,
            ),
            Oppdrag(
                "K2", "Bruker M", "Kirkeveien 166, Oslo", 20,
                10.7346, 59.9367, alle, Besoksrunde.KVELD,
            ),
            Oppdrag(
                "K3", "Bruker N", "Sognsveien 75 A, Oslo", 40,
                10.7342, 59.9489, alle, Besoksrunde.KVELD,
            ),
        ],
    }


def lag_alle_testansatte() -> list[Ansatt]:
    """Lag hovedlisten med alle ansatte, uavhengig av hvem som er på jobb."""

    return [
        Ansatt("1", "Ansatt 1", Kvalifikasjonsniva.KVALIFISERT),
        Ansatt(
            "2",
            "Ansatt 2",
            Kvalifikasjonsniva.UTEN_HELSEFAGLIG_UTDANNING,
        ),
        Ansatt("3", "Ansatt 3", Kvalifikasjonsniva.KVALIFISERT),
    ]


def lag_aktiv_bemanning() -> dict[Besoksrunde, set[str]]:
    """Angi hvilke ansatte som er på jobb i hver besøksrunde.

    Settet inneholder ansatt-id-er fra hovedlisten. Dette er eksempeldata for
    én dag og kan senere erstattes av en faktisk arbeidsplan.
    """

    return {
        Besoksrunde.DAG: {"1", "2"},
        Besoksrunde.LUNSJ: {"1", "3"},
        Besoksrunde.MIDDAG: {"2", "3"},
        Besoksrunde.KVELD: {"1", "2", "3"},
    }


def hent_aktive_ansatte(
    alle_ansatte: list[Ansatt],
    aktive_ansatt_ider: set[str],
) -> list[Ansatt]:
    """Filtrer hovedlisten til ansatte som er på jobb i valgt runde."""

    aktive_ansatte = [
        ansatt for ansatt in alle_ansatte if ansatt.id in aktive_ansatt_ider
    ]
    if not aktive_ansatte:
        raise RuntimeError("Ingen ansatte er satt opp på valgt besøksrunde.")
    return aktive_ansatte


def formater_klokkeslett(minutter_etter_midnatt: int) -> str:
    """Gjør for eksempel 510 minutter om til teksten 08:30."""

    timer, minutter = divmod(minutter_etter_midnatt, 60)
    return f"{timer:02d}:{minutter:02d}"


def velg_besoksrunde() -> Besoksrunde:
    """Be brukeren velge hvilken besøksrunde som skal planlegges."""

    runder = list(Besoksrunde)
    print("Velg besøksrunde:\n")
    for nummer, runde in enumerate(runder, start=1):
        print(
            f"{nummer}. {runde.visningsnavn} "
            f"({formater_klokkeslett(runde.starttid)}–"
            f"{formater_klokkeslett(runde.sluttid)})"
        )

    while True:
        try:
            valg = int(input("\nSkriv nummeret på besøksrunden: "))
        except ValueError:
            print(f"Velg et tall fra 1 til {len(runder)}.")
            continue

        if 1 <= valg <= len(runder):
            return runder[valg - 1]

        print(f"Velg et tall fra 1 til {len(runder)}.")


def skriv_ut_resultat(
    ruter: list[AnsattRute],
    besoksrunde: Besoksrunde,
) -> None:
    """Presenter rutene og marker besøk etter rundens ønskede slutt."""

    print(
        f"\nBesøksrunde: {besoksrunde.visningsnavn} "
        f"({formater_klokkeslett(besoksrunde.starttid)}–"
        f"{formater_klokkeslett(besoksrunde.sluttid)})\n"
    )

    for rute in ruter:
        print(f"{rute.ansatt.navn} – start: Depot")
        print(
            "Runden starter: "
            f"{formater_klokkeslett(besoksrunde.starttid)}\n"
        )
        print(f"Kvalifikasjon: {rute.ansatt.kvalifikasjon.visningsnavn}\n")

        navarende_tid = besoksrunde.starttid
        for nummer, ((oppdrag, kjoretid), tider) in enumerate(
            zip(rute.stopp, rute.tidspunkter),
            start=1,
        ):
            ankomst, avslutning = tider
            ventetid = ankomst - (navarende_tid + kjoretid)
            forsinkelse = max(0, ankomst - besoksrunde.sluttid)

            print(f"{nummer}. {oppdrag.navn}")
            print(f"   Adresse: {oppdrag.adresse}")
            print(f"   Kjøring: {kjoretid} min")
            if ventetid > 0:
                print(f"   Ventetid: {ventetid} min")
            print(f"   Ankomst: {formater_klokkeslett(ankomst)}")
            if forsinkelse > 0:
                print(f"   FORSINKET: {forsinkelse} min etter rundens slutt")
            print(f"   Oppdrag: {oppdrag.varighet} min")
            print(f"   Avsluttet: {formater_klokkeslett(avslutning)}")
            if oppdrag.antall_ansatte > 1:
                print(
                    f"   Dobbeltbemannet: krever {oppdrag.antall_ansatte} "
                    "ansatte samtidig"
                )
                if (
                    oppdrag.minimum_kvalifikasjon
                    is Kvalifikasjonsniva.KVALIFISERT
                ):
                    print("   Minst én av de ansatte må være kvalifisert")

            if oppdrag.kritisk_tidligste_start is not None:
                print(
                    "   Kritisk tidsvindu: "
                    f"{formater_klokkeslett(oppdrag.kritisk_tidligste_start)}–"
                    f"{formater_klokkeslett(oppdrag.kritisk_seneste_start)}"
                )

            if oppdrag.antall_ansatte == 1:
                print(
                    "   Krav: "
                    f"{oppdrag.minimum_kvalifikasjon.visningsnavn}"
                )
            print()
            navarende_tid = avslutning

        print("Retur: Depot")
        print(f"   Kjøring: {rute.kjoretid_til_depot} min")
        print(
            f"   Tilbake: {formater_klokkeslett(rute.tilbake_pa_depot_tid)}\n"
        )
        print(f"Total kjøretid: {rute.total_kjoretid} min")
        print(f"Total arbeidstid: {rute.total_arbeidstid} min")
        print("-" * 40)

    arbeidstider = [rute.total_arbeidstid for rute in ruter]
    forskjell = max(arbeidstider) - min(arbeidstider)
    print(f"Forskjell i arbeidstid: {forskjell} min")


def main() -> None:
    """Velg én besøksrunde, planlegg den og skriv ut resultatet."""

    api_nokkel = os.environ.get("ORS_API_KEY")
    if not api_nokkel:
        raise RuntimeError(
            "Mangler API-nøkkel. Sett miljøvariabelen ORS_API_KEY før du kjører."
        )

    besoksrunde = velg_besoksrunde()
    oppdrag = lag_testoppdrag_per_runde()[besoksrunde]
    alle_ansatte = lag_alle_testansatte()
    aktive_ansatt_ider = lag_aktiv_bemanning()[besoksrunde]
    ansatte = hent_aktive_ansatte(alle_ansatte, aktive_ansatt_ider)

    # Bare stedene i valgt besøksrunde sendes til OpenRouteService.
    kjoretider = hent_kjoretidsmatrise(
        oppdrag,
        DEPOT_KOORDINATER,
        api_nokkel,
    )
    ruter = planlegg_ruter(
        ansatte,
        oppdrag,
        kjoretider,
        besoksrunde,
    )
    skriv_ut_resultat(ruter, besoksrunde)


if __name__ == "__main__":
    main()

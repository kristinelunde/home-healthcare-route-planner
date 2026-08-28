"""Tester av de viktigste reglene i prototypen."""

import io
import unittest
from unittest.mock import patch

from ansatt import Ansatt
from besoksrunde import Besoksrunde
from gui import _bruk_midlertidige_oppdragsvalg
from kvalifikasjon import Kvalifikasjonsniva
from main import hent_aktive_ansatte
from openrouteservice import hent_koordinater
from oppdrag import Oppdrag
from ruteplanlegger import planlegg_ruter


KVALIFISERT = Kvalifikasjonsniva.KVALIFISERT
ALLE = Kvalifikasjonsniva.UTEN_HELSEFAGLIG_UTDANNING


def lag_oppdrag(
    oppdrag_id: str,
    navn: str,
    kvalifikasjon: Kvalifikasjonsniva = ALLE,
    antall_ansatte: int = 1,
    kritisk_start: int = None,
    kritisk_slutt: int = None,
) -> Oppdrag:
    """Lag et lite testoppdrag i dagrunden."""

    return Oppdrag(
        id=oppdrag_id,
        navn=navn,
        adresse=f"Testadresse {oppdrag_id}",
        varighet=20,
        lengdegrad=10.75,
        breddegrad=59.92,
        minimum_kvalifikasjon=kvalifikasjon,
        besoksrunde=Besoksrunde.DAG,
        kritisk_tidligste_start=kritisk_start,
        kritisk_seneste_start=kritisk_slutt,
        antall_ansatte=antall_ansatte,
    )


def lag_kjoretidsmatrise(oppdrag: list[Oppdrag]) -> dict[str, dict[str, int]]:
    """Lag en fast matrise slik at testene ikke bruker internett."""

    steder = ["Depot"] + [ett_oppdrag.id for ett_oppdrag in oppdrag]
    return {
        fra_sted: {
            til_sted: 0 if fra_sted == til_sted else 5
            for til_sted in steder
        }
        for fra_sted in steder
    }


class TestRuteplanlegging(unittest.TestCase):
    """Kontroller de viktigste OR-Tools-begrensningene samlet."""

    def test_kvalifikasjon_tomannsoppdrag_og_kritisk_tid(self) -> None:
        ansatte = [
            Ansatt("K", "Kvalifisert ansatt", KVALIFISERT),
            Ansatt("U", "Ukvalifisert ansatt", ALLE),
        ]
        oppdrag = [
            lag_oppdrag(
                "A",
                "Kritisk besøk",
                kvalifikasjon=KVALIFISERT,
                kritisk_start=9 * 60,
                kritisk_slutt=9 * 60 + 15,
            ),
            lag_oppdrag(
                "B",
                "Tomannsbesøk",
                kvalifikasjon=KVALIFISERT,
                antall_ansatte=2,
            ),
        ]

        ruter = planlegg_ruter(
            ansatte,
            oppdrag,
            lag_kjoretidsmatrise(oppdrag),
            Besoksrunde.DAG,
        )

        besok = []
        for rute in ruter:
            for (stopp, _), (ankomst, _) in zip(
                rute.stopp,
                rute.tidspunkter,
            ):
                besok.append((rute.ansatt, stopp, ankomst))

        kritisk = [resultat for resultat in besok if resultat[1].id == "A"]
        self.assertEqual(len(kritisk), 1)
        self.assertEqual(kritisk[0][0].kvalifikasjon, KVALIFISERT)
        self.assertGreaterEqual(kritisk[0][2], 9 * 60)
        self.assertLessEqual(kritisk[0][2], 9 * 60 + 15)

        tomannsbesok = [
            resultat for resultat in besok if resultat[1].id == "B"
        ]
        self.assertEqual(len(tomannsbesok), 2)
        self.assertEqual(len({resultat[0].id for resultat in tomannsbesok}), 2)
        self.assertEqual(len({resultat[2] for resultat in tomannsbesok}), 1)
        self.assertTrue(
            any(
                resultat[0].kvalifikasjon == KVALIFISERT
                for resultat in tomannsbesok
            )
        )


class TestDatabehandling(unittest.TestCase):
    """Kontroller filtrering og midlertidige GUI-valg."""

    def test_bare_aktive_ansatte_hentes_ut(self) -> None:
        ansatte = [
            Ansatt("1", "Ansatt 1", KVALIFISERT),
            Ansatt("2", "Ansatt 2", ALLE),
            Ansatt("3", "Ansatt 3", ALLE),
        ]

        aktive = hent_aktive_ansatte(ansatte, {"1", "3"})

        self.assertEqual([ansatt.id for ansatt in aktive], ["1", "3"])

    def test_fjernet_oppdrag_sendes_ikke_til_planlegging(self) -> None:
        oppdrag = [
            lag_oppdrag("A", "Skal være med"),
            lag_oppdrag("B", "Skal fjernes"),
        ]
        valg = [
            {
                "id": "A",
                "aktiv": True,
                "varighet": 20,
                "kvalifikasjon": ALLE.name,
                "antall_ansatte": 1,
                "kritisk_start": None,
                "kritisk_slutt": None,
            },
            {
                "id": "B",
                "aktiv": False,
                "varighet": 20,
                "kvalifikasjon": ALLE.name,
                "antall_ansatte": 1,
                "kritisk_start": None,
                "kritisk_slutt": None,
            },
        ]

        valgte = _bruk_midlertidige_oppdragsvalg(
            oppdrag,
            valg,
            Besoksrunde.DAG,
        )

        self.assertEqual([ett_oppdrag.id for ett_oppdrag in valgte], ["A"])


class TestOpenRouteService(unittest.TestCase):
    """Kontroller geokoding uten et ekte API-kall."""

    def test_geokoding_returnerer_lengdegrad_og_breddegrad(self) -> None:
        api_svar = io.BytesIO(
            b'{"features":[{"geometry":{"coordinates":[10.75,59.92]}}]}'
        )

        with patch("openrouteservice.urlopen", return_value=api_svar) as kall:
            koordinater = hent_koordinater("Testveien 1, Oslo", "testnokkel")

        self.assertEqual(koordinater, (10.75, 59.92))
        request = kall.call_args.args[0]
        self.assertIn("boundary.country=NO", request.full_url)
        self.assertEqual(request.headers["Authorization"], "testnokkel")


if __name__ == "__main__":
    unittest.main()

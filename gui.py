"""Lokalt nettleserbasert GUI for ruteplanleggeren."""

import json
import os
import errno
import threading
import webbrowser
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from besoksrunde import Besoksrunde
from main import (
    DEPOT_KOORDINATER,
    formater_klokkeslett,
    hent_aktive_ansatte,
    lag_aktiv_bemanning,
    lag_alle_testansatte,
    lag_testoppdrag_per_runde,
)
from kvalifikasjon import Kvalifikasjonsniva
from openrouteservice import hent_kjoretidsmatrise, hent_koordinater
from oppdrag import Oppdrag
from ruteplanlegger import planlegg_ruter


GUI_FIL = Path(__file__).with_name("gui.html")
VERT = "127.0.0.1"
PORT = 8000


def lag_gui_data() -> dict:
    """Lag dataene GUI-et trenger før en rute blir planlagt."""

    alle_ansatte = lag_alle_testansatte()
    aktiv_bemanning = lag_aktiv_bemanning()
    oppdrag_per_runde = lag_testoppdrag_per_runde()
    runder = []

    for runde in Besoksrunde:
        aktive = hent_aktive_ansatte(alle_ansatte, aktiv_bemanning[runde])
        runder.append(
            {
                "id": runde.name,
                "navn": runde.visningsnavn,
                "start": formater_klokkeslett(runde.starttid),
                "slutt": formater_klokkeslett(runde.sluttid),
                "ansatte": [
                    {
                        "navn": ansatt.navn,
                        "kvalifikasjon": ansatt.kvalifikasjon.visningsnavn,
                    }
                    for ansatt in aktive
                ],
                "oppdrag": [
                    {
                        "id": oppdrag.id,
                        "navn": oppdrag.navn,
                        "adresse": oppdrag.adresse,
                        "varighet": oppdrag.varighet,
                        "kvalifikasjon": (
                            oppdrag.minimum_kvalifikasjon.visningsnavn
                        ),
                        "kvalifikasjon_id": oppdrag.minimum_kvalifikasjon.name,
                        "antall_ansatte": oppdrag.antall_ansatte,
                        "kritisk": _kritisk_tidsvindu(oppdrag),
                        "kritisk_start": oppdrag.kritisk_tidligste_start,
                        "kritisk_slutt": oppdrag.kritisk_seneste_start,
                    }
                    for oppdrag in oppdrag_per_runde[runde]
                ],
            }
        )

    return {"runder": runder}


def planlegg_for_gui(
    runde_navn: str,
    api_nokkel: str,
    oppdragsvalg: list[dict] = None,
) -> dict:
    """Planlegg én valgt runde og gjør resultatet om til JSON-data."""

    try:
        runde = Besoksrunde[runde_navn]
    except KeyError as feil:
        raise ValueError("Ukjent besøksrunde.") from feil

    alle_ansatte = lag_alle_testansatte()
    aktive = hent_aktive_ansatte(
        alle_ansatte,
        lag_aktiv_bemanning()[runde],
    )
    oppdragsvalg = _fyll_inn_manglende_koordinater(
        oppdragsvalg,
        api_nokkel,
    )
    oppdrag = _bruk_midlertidige_oppdragsvalg(
        lag_testoppdrag_per_runde()[runde],
        oppdragsvalg,
        runde,
    )

    if oppdrag:
        kjoretider = hent_kjoretidsmatrise(
            oppdrag,
            DEPOT_KOORDINATER,
            api_nokkel,
        )
    else:
        # En tom runde trenger ikke et API-kall.
        kjoretider = {"Depot": {"Depot": 0}}
    ruter = planlegg_ruter(aktive, oppdrag, kjoretider, runde)

    return {
        "runde": runde.visningsnavn,
        "ruter": [
            {
                "ansatt": rute.ansatt.navn,
                "kvalifikasjon": rute.ansatt.kvalifikasjon.visningsnavn,
                "stopp": [
                    {
                        "navn": stopp.navn,
                        "adresse": stopp.adresse,
                        "ankomst": formater_klokkeslett(tider[0]),
                        "avslutning": formater_klokkeslett(tider[1]),
                        "kjoretid": kjoretid,
                        "varighet": stopp.varighet,
                        "antall_ansatte": stopp.antall_ansatte,
                        "forsinkelse": max(0, tider[0] - runde.sluttid),
                        "kritisk": _kritisk_tidsvindu(stopp),
                    }
                    for (stopp, kjoretid), tider in zip(
                        rute.stopp,
                        rute.tidspunkter,
                    )
                ],
                "tilbake": formater_klokkeslett(
                    rute.tilbake_pa_depot_tid
                ),
                "total_kjoretid": rute.total_kjoretid,
                "total_arbeidstid": rute.total_arbeidstid,
            }
            for rute in ruter
        ],
    }


def _fyll_inn_manglende_koordinater(
    oppdragsvalg: list[dict] = None,
    api_nokkel: str = "",
) -> list[dict]:
    """Geokod aktive, nye oppdrag som bare har adresse."""

    if oppdragsvalg is None:
        return None

    oppdaterte_valg = []
    for opprinnelig_valg in oppdragsvalg:
        valg = opprinnelig_valg.copy()
        mangler_koordinater = (
            valg.get("lengdegrad") is None
            or valg.get("breddegrad") is None
        )
        if (
            valg.get("ny", False)
            and valg.get("aktiv", True)
            and mangler_koordinater
        ):
            lengdegrad, breddegrad = hent_koordinater(
                str(valg.get("adresse", "")).strip(),
                api_nokkel,
            )
            valg["lengdegrad"] = lengdegrad
            valg["breddegrad"] = breddegrad
        oppdaterte_valg.append(valg)

    return oppdaterte_valg


def _bruk_midlertidige_oppdragsvalg(
    oppdrag: list[Oppdrag],
    oppdragsvalg: list[dict] = None,
    besoksrunde: Besoksrunde = None,
) -> list[Oppdrag]:
    """Bruk midlertidig varighet og filtrering fra GUI-et."""

    if oppdragsvalg is None:
        return oppdrag

    valg_per_id = {valg["id"]: valg for valg in oppdragsvalg}
    ukjente_ider = {
        oppdrag_id
        for oppdrag_id, valg in valg_per_id.items()
        if oppdrag_id not in {ett_oppdrag.id for ett_oppdrag in oppdrag}
        and not valg.get("ny", False)
    }
    if ukjente_ider:
        raise ValueError("GUI-et sendte et ukjent oppdrag.")

    valgte_oppdrag = []
    for ett_oppdrag in oppdrag:
        valg = valg_per_id.get(ett_oppdrag.id)
        if valg is None:
            valgte_oppdrag.append(ett_oppdrag)
            continue

        if not valg.get("aktiv", True):
            continue

        try:
            varighet = int(valg["varighet"])
        except (KeyError, TypeError, ValueError) as feil:
            raise ValueError(
                f"Varigheten for {ett_oppdrag.navn} må være et heltall."
            ) from feil

        if varighet < 1:
            raise ValueError(
                f"Varigheten for {ett_oppdrag.navn} må være minst 1 minutt."
            )

        try:
            minimum_kvalifikasjon = Kvalifikasjonsniva[
                valg.get(
                    "kvalifikasjon",
                    ett_oppdrag.minimum_kvalifikasjon.name,
                )
            ]
            antall_ansatte = int(
                valg.get("antall_ansatte", ett_oppdrag.antall_ansatte)
            )
        except (KeyError, TypeError, ValueError) as feil:
            raise ValueError(
                f"Ugyldig kompetanse eller bemanning for {ett_oppdrag.navn}."
            ) from feil

        if antall_ansatte < 1:
            raise ValueError(
                f"{ett_oppdrag.navn} må kreve minst én ansatt."
            )

        kritisk_start = valg.get("kritisk_start")
        kritisk_slutt = valg.get("kritisk_slutt")
        if kritisk_start is not None or kritisk_slutt is not None:
            try:
                kritisk_start = int(kritisk_start)
                kritisk_slutt = int(kritisk_slutt)
            except (TypeError, ValueError) as feil:
                raise ValueError(
                    f"Ugyldig kritisk tid for {ett_oppdrag.navn}."
                ) from feil

        valgte_oppdrag.append(
            replace(
                ett_oppdrag,
                varighet=varighet,
                minimum_kvalifikasjon=minimum_kvalifikasjon,
                antall_ansatte=antall_ansatte,
                kritisk_tidligste_start=kritisk_start,
                kritisk_seneste_start=kritisk_slutt,
            )
        )

    for valg in oppdragsvalg:
        if valg.get("ny", False) and valg.get("aktiv", True):
            valgte_oppdrag.append(_lag_nytt_oppdrag(valg, besoksrunde))

    return valgte_oppdrag


def _lag_nytt_oppdrag(
    valg: dict,
    besoksrunde: Besoksrunde,
) -> Oppdrag:
    """Valider og opprett et midlertidig oppdrag fra GUI-skjemaet."""

    if besoksrunde is None:
        raise ValueError("Nytt oppdrag mangler besøksrunde.")

    navn = str(valg.get("navn", "")).strip()
    adresse = str(valg.get("adresse", "")).strip()
    if not navn or not adresse:
        raise ValueError("Nytt oppdrag må ha både brukernavn og adresse.")

    try:
        varighet = int(valg["varighet"])
        antall_ansatte = int(valg["antall_ansatte"])
        lengdegrad = float(valg["lengdegrad"])
        breddegrad = float(valg["breddegrad"])
        kvalifikasjon = Kvalifikasjonsniva[valg["kvalifikasjon"]]
    except (KeyError, TypeError, ValueError) as feil:
        raise ValueError("Nytt oppdrag har ugyldige eller manglende felt.") from feil

    if varighet < 1 or antall_ansatte < 1:
        raise ValueError("Varighet og antall ansatte må være minst 1.")
    if not -180 <= lengdegrad <= 180 or not -90 <= breddegrad <= 90:
        raise ValueError("Lengdegrad eller breddegrad er utenfor gyldig område.")

    kritisk_start = valg.get("kritisk_start")
    kritisk_slutt = valg.get("kritisk_slutt")
    if kritisk_start is not None or kritisk_slutt is not None:
        try:
            kritisk_start = int(kritisk_start)
            kritisk_slutt = int(kritisk_slutt)
        except (TypeError, ValueError) as feil:
            raise ValueError("Nytt oppdrag har ugyldig kritisk tid.") from feil

    return Oppdrag(
        id=str(valg["id"]),
        navn=navn,
        adresse=adresse,
        varighet=varighet,
        lengdegrad=lengdegrad,
        breddegrad=breddegrad,
        minimum_kvalifikasjon=kvalifikasjon,
        besoksrunde=besoksrunde,
        kritisk_tidligste_start=kritisk_start,
        kritisk_seneste_start=kritisk_slutt,
        antall_ansatte=antall_ansatte,
    )


def _kritisk_tidsvindu(oppdrag: Oppdrag) -> str:
    """Formater et kritisk tidsvindu, eller returner tom tekst."""

    if oppdrag.kritisk_tidligste_start is None:
        return ""
    return (
        f"{formater_klokkeslett(oppdrag.kritisk_tidligste_start)}–"
        f"{formater_klokkeslett(oppdrag.kritisk_seneste_start)}"
    )


class GUIHandler(BaseHTTPRequestHandler):
    """Server HTML-siden og de to lokale API-endepunktene."""

    def do_GET(self) -> None:
        if self.path == "/":
            self._avbryt_planlagt_stopp()
            self._send_bytes(GUI_FIL.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/data":
            self._send_json(lag_gui_data())
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/stopp":
            self._send_bytes(b"", "text/plain; charset=utf-8", status=204)
            # Vent litt før stopp. Ved en vanlig oppdatering rekker den nye
            # siden å avbryte stoppet; ved lukking med X blir serveren stoppet.
            gammel_timer = getattr(self.server, "stopp_timer", None)
            if gammel_timer is not None:
                gammel_timer.cancel()
            stopp_timer = threading.Timer(
                2.0,
                target=self.server.shutdown,
            )
            stopp_timer.daemon = True
            self.server.stopp_timer = stopp_timer
            stopp_timer.start()
            return

        if self.path != "/api/planlegg":
            self.send_error(404)
            return

        try:
            lengde = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(lengde))
            api_nokkel = os.environ.get("ORS_API_KEY")
            if not api_nokkel:
                raise RuntimeError(
                    "Mangler API-nøkkel. Sett ORS_API_KEY før GUI-et startes."
                )
            resultat = planlegg_for_gui(
                data["runde"],
                api_nokkel,
                data.get("oppdrag"),
            )
            self._send_json(resultat)
        except (KeyError, ValueError, RuntimeError, json.JSONDecodeError) as feil:
            self._send_json({"feil": str(feil)}, status=400)

    def _send_json(self, data: dict, status: int = 200) -> None:
        innhold = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_bytes(innhold, "application/json; charset=utf-8", status)

    def _send_bytes(
        self,
        innhold: bytes,
        innholdstype: str,
        status: int = 200,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", innholdstype)
        self.send_header("Content-Length", str(len(innhold)))
        self.end_headers()
        self.wfile.write(innhold)

    def log_message(self, format: str, *args: object) -> None:
        """Hold terminalutskriften ryddig under vanlig GUI-bruk."""

    def _avbryt_planlagt_stopp(self) -> None:
        """Behold serveren når nettleseren bare oppdaterer siden."""

        stopp_timer = getattr(self.server, "stopp_timer", None)
        if stopp_timer is not None:
            stopp_timer.cancel()
            self.server.stopp_timer = None

def main() -> None:
    """Start den lokale GUI-serveren."""

    server = _start_server_pa_ledig_port()
    valgt_port = server.server_address[1]
    adresse = f"http://{VERT}:{valgt_port}"
    print(f"GUI-et kjører på {adresse}")
    print("Trykk Ctrl+C for å stoppe.")
    webbrowser.open(adresse)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGUI-et er stoppet.")
    finally:
        server.server_close()


def _start_server_pa_ledig_port() -> ThreadingHTTPServer:
    """Prøv port 8000–8009 og bruk den første som er ledig."""

    for port in range(PORT, PORT + 10):
        try:
            return ThreadingHTTPServer((VERT, port), GUIHandler)
        except OSError as feil:
            if feil.errno != errno.EADDRINUSE:
                raise

    raise RuntimeError("Fant ingen ledig GUI-port mellom 8000 og 8009.")


if __name__ == "__main__":
    main()

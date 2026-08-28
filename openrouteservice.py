"""Henting av kjøretider fra OpenRouteService.

Modulen bruker bare Pythons standardbibliotek. API-nøkkelen sendes inn fra
programmet og lagres derfor ikke i kildekoden.
"""

import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from oppdrag import Oppdrag
from ruteplanlegger import Kjoretidsmatrise


MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/driving-car"
GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"


def hent_koordinater(
    adresse: str,
    api_nokkel: str,
) -> tuple[float, float]:
    """Finn lengde- og breddegrad for en norsk adresse."""

    parametere = urlencode(
        {
            "text": adresse,
            "size": 1,
            "boundary.country": "NO",
        }
    )
    request = Request(
        f"{GEOCODE_URL}?{parametere}",
        headers={"Authorization": api_nokkel},
        method="GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            response_data = json.load(response)
    except HTTPError as error:
        detalj = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenRouteService svarte med HTTP {error.code}: {detalj}"
        ) from error
    except URLError as error:
        raise RuntimeError(
            f"Kunne ikke koble til OpenRouteService: {error.reason}"
        ) from error

    features = response_data.get("features", [])
    if not features:
        raise RuntimeError(f"Fant ingen koordinater for adressen: {adresse}")

    koordinater = features[0].get("geometry", {}).get("coordinates")
    if not koordinater or len(koordinater) < 2:
        raise RuntimeError(
            f"OpenRouteService returnerte ugyldige koordinater for: {adresse}"
        )

    # OpenRouteService returnerer [lengdegrad, breddegrad].
    return float(koordinater[0]), float(koordinater[1])


def hent_kjoretidsmatrise(
    oppdrag: list[Oppdrag],
    depot_koordinater: tuple[float, float],
    api_nokkel: str,
) -> Kjoretidsmatrise:
    """Hent kjøretid mellom depotet og alle oppdragene.

    OpenRouteService forventer koordinater i rekkefølgen
    [lengdegrad, breddegrad] og returnerer varigheter i sekunder.
    Resultatet konverteres til hele minutter, slik resten av programmet bruker.
    """

    stedsnavn = ["Depot"] + [oppdrag.id for oppdrag in oppdrag]
    koordinater = [list(depot_koordinater)] + [
        [oppdrag.lengdegrad, oppdrag.breddegrad] for oppdrag in oppdrag
    ]

    request_data = json.dumps(
        {
            "locations": koordinater,
            "metrics": ["duration"],
        }
    ).encode("utf-8")

    request = Request(
        MATRIX_URL,
        data=request_data,
        headers={
            "Authorization": api_nokkel,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            response_data = json.load(response)
    except HTTPError as error:
        # API-et sender ofte en nyttig feilmelding i responsen.
        detalj = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenRouteService svarte med HTTP {error.code}: {detalj}"
        ) from error
    except URLError as error:
        raise RuntimeError(
            f"Kunne ikke koble til OpenRouteService: {error.reason}"
        ) from error

    varigheter = response_data.get("durations")
    if not varigheter:
        raise RuntimeError("OpenRouteService returnerte ingen kjøretider.")

    kjoretider: Kjoretidsmatrise = {}
    for fra_indeks, fra_sted in enumerate(stedsnavn):
        kjoretider[fra_sted] = {}

        for til_indeks, til_sted in enumerate(stedsnavn):
            sekunder = varigheter[fra_indeks][til_indeks]
            if sekunder is None:
                raise RuntimeError(
                    f"Fant ingen kjørbar rute fra {fra_sted} til {til_sted}."
                )

            # Vi runder opp slik at estimert arbeidstid ikke blir for kort.
            kjoretider[fra_sted][til_sted] = math.ceil(sekunder / 60)

    return kjoretider

"""Ruteplanlegging for flere ansatte ved hjelp av OR-Tools."""

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from ansatt import Ansatt, AnsattRute
from besoksrunde import Besoksrunde
from kvalifikasjon import Kvalifikasjonsniva
from oppdrag import Oppdrag


Kjoretidsmatrise = dict[str, dict[str, int]]


def planlegg_ruter(
    ansatte: list[Ansatt],
    oppdrag: list[Oppdrag],
    kjoretider: Kjoretidsmatrise,
    besoksrunde: Besoksrunde,
) -> list[AnsattRute]:
    """Fordel oppdrag og finn ruter med OR-Tools.

    Hver ansatt behandles som ett kjøretøy. Alle starter og slutter på
    depotet, og hvert oppdrag får det antallet ansatte som oppdraget krever.

    OR-Tools minimerer samlet kjøretid. I tillegg får den lengste arbeidsruten
    en ekstra kostnad, slik at oppdragene blir fordelt noenlunde jevnt.
    Arbeidstid består av kjøretid, oppdragsvarighet og eventuell ventetid.
    Rundens slutt er et mykt mål, mens individuelle kritiske tidsvinduer er
    absolutte krav.
    """

    if not ansatte:
        raise ValueError("Minst én ansatt er nødvendig for å planlegge ruter.")

    for ett_oppdrag in oppdrag:
        if ett_oppdrag.antall_ansatte < 1:
            raise ValueError(
                f"{ett_oppdrag.navn} må kreve minst én ansatt."
            )

        ansatte_med_riktig_kvalifikasjon = [
            ansatt
            for ansatt in ansatte
            if ansatt.kvalifikasjon >= ett_oppdrag.minimum_kvalifikasjon
        ]
        if len(ansatte) < ett_oppdrag.antall_ansatte:
            raise RuntimeError(
                f"{ett_oppdrag.navn} krever {ett_oppdrag.antall_ansatte} "
                "ansatte samtidig, men det finnes ikke nok aktive ansatte."
            )

        if not ansatte_med_riktig_kvalifikasjon:
            raise RuntimeError(
                f"Ingen aktive ansatte har nødvendig kvalifikasjon for "
                f"{ett_oppdrag.navn}."
            )

        if ett_oppdrag.besoksrunde is not besoksrunde:
            raise ValueError(
                f"{ett_oppdrag.navn} tilhører ikke valgt besøksrunde."
            )

        har_tidligste = ett_oppdrag.kritisk_tidligste_start is not None
        har_seneste = ett_oppdrag.kritisk_seneste_start is not None
        if har_tidligste != har_seneste:
            raise ValueError(
                f"{ett_oppdrag.navn} må ha både tidligste og seneste "
                "start for et kritisk tidsvindu."
            )

        if (
            har_tidligste
            and ett_oppdrag.kritisk_tidligste_start
            > ett_oppdrag.kritisk_seneste_start
        ):
            raise ValueError(
                f"Ugyldig kritisk tidsvindu for {ett_oppdrag.navn}."
            )

    # Et tomannsoppdrag representeres av to interne noder med samme oppdrag.
    # Gruppene brukes senere til å kreve ulik ansatt og lik ankomsttid.
    planleggingsoppdrag: list[Oppdrag] = []
    interne_minimumskrav: list[Kvalifikasjonsniva] = []
    samtidige_nodegrupper: list[list[int]] = []
    for ett_oppdrag in oppdrag:
        nodegruppe: list[int] = []
        for plass in range(ett_oppdrag.antall_ansatte):
            planleggingsoppdrag.append(ett_oppdrag)
            # Første plass må oppfylle oppdragets krav. Eventuelle øvrige
            # plasser er assistenter og kan fylles av alle ansatte.
            interne_minimumskrav.append(
                ett_oppdrag.minimum_kvalifikasjon
                if plass == 0
                else Kvalifikasjonsniva.UTEN_HELSEFAGLIG_UTDANNING
            )
            nodegruppe.append(len(planleggingsoppdrag))
        if len(nodegruppe) > 1:
            samtidige_nodegrupper.append(nodegruppe)

    # Node 0 er depotet. De øvrige nodene er de interne planleggingsoppdragene.
    stedsnavn = ["Depot"] + [
        ett_oppdrag.id for ett_oppdrag in planleggingsoppdrag
    ]
    antall_steder = len(stedsnavn)
    antall_ansatte = len(ansatte)

    manager = pywrapcp.RoutingIndexManager(
        antall_steder,
        antall_ansatte,
        0,  # Alle ansatte starter og slutter ved node 0: Depot.
    )
    routing = pywrapcp.RoutingModel(manager)

    # Samme ansatt kan ikke fylle begge plassene i et tomannsoppdrag.
    for nodegruppe in samtidige_nodegrupper:
        for posisjon, node_a in enumerate(nodegruppe):
            for node_b in nodegruppe[posisjon + 1:]:
                routing.solver().Add(
                    routing.VehicleVar(manager.NodeToIndex(node_a))
                    != routing.VehicleVar(manager.NodeToIndex(node_b))
                )

    # Begrens hvert oppdrag til ansatte med tilstrekkelig kvalifikasjon.
    for oppdrag_indeks, minimumskrav in enumerate(
        interne_minimumskrav,
        start=1,
    ):
        tillatte_ansatte = [
            ansatt_indeks
            for ansatt_indeks, ansatt in enumerate(ansatte)
            if ansatt.kvalifikasjon >= minimumskrav
        ]

        intern_indeks = manager.NodeToIndex(oppdrag_indeks)

        # OR-Tools kaller ansatte/kjøretøy for vehicle i denne variabelen.
        # Vi utelukker hver ansatt som ikke står i listen over tillatte.
        for ansatt_indeks in range(antall_ansatte):
            if ansatt_indeks not in tillatte_ansatte:
                routing.solver().Add(
                    routing.VehicleVar(intern_indeks) != ansatt_indeks
                )

    def kjoretid_callback(fra_indeks: int, til_indeks: int) -> int:
        """Gi OR-Tools kjøretiden mellom to interne indekser."""

        fra_node = manager.IndexToNode(fra_indeks)
        til_node = manager.IndexToNode(til_indeks)
        return kjoretider[stedsnavn[fra_node]][stedsnavn[til_node]]

    kjoretid_callback_indeks = routing.RegisterTransitCallback(kjoretid_callback)

    # Dette er hovedkostnaden: summen av all kjøring skal være så lav som mulig.
    routing.SetArcCostEvaluatorOfAllVehicles(kjoretid_callback_indeks)

    def arbeidstid_callback(fra_indeks: int, til_indeks: int) -> int:
        """Beregn kjøring pluss varigheten ved stedet vi forlater."""

        fra_node = manager.IndexToNode(fra_indeks)
        til_node = manager.IndexToNode(til_indeks)
        kjoretid = kjoretider[stedsnavn[fra_node]][stedsnavn[til_node]]

        # Depotet har ingen oppdragsvarighet. Node 1 tilsvarer første interne
        # planleggingsoppdrag.
        oppdragsvarighet = (
            0
            if fra_node == 0
            else planleggingsoppdrag[fra_node - 1].varighet
        )
        return kjoretid + oppdragsvarighet

    arbeidstid_callback_indeks = routing.RegisterTransitCallback(
        arbeidstid_callback
    )

    # En romslig øvre grense gjør dimensjonen gyldig uten å innføre et krav om
    # maksimal skiftlengde ennå.
    storste_kjoretid = max(
        tid for rad in kjoretider.values() for tid in rad.values()
    )
    maksimal_arbeidstid = (
        sum(ett_oppdrag.varighet for ett_oppdrag in planleggingsoppdrag)
        + storste_kjoretid * (len(planleggingsoppdrag) + 1)
    )

    seneste_kritiske_tid = max(
        [besoksrunde.starttid]
        + [
            ett_oppdrag.kritisk_seneste_start
            for ett_oppdrag in planleggingsoppdrag
            if ett_oppdrag.kritisk_seneste_start is not None
        ]
    )

    # OR-Tools krever en endelig teknisk øvre grense. Det ekstra døgnet er
    # bare solverplass til venting og er ikke en maksimal arbeidslengde.
    maksimal_ventetid = 24 * 60
    teknisk_sluttgrense = (
        max(besoksrunde.starttid, seneste_kritiske_tid)
        + maksimal_arbeidstid
        + maksimal_ventetid
    )

    routing.AddDimension(
        arbeidstid_callback_indeks,
        maksimal_ventetid,
        teknisk_sluttgrense,
        False,                  # Startverdien settes til valgt rundestart.
        "Arbeidstid",
    )
    arbeidstid_dimensjon = routing.GetDimensionOrDie("Arbeidstid")

    # CumulVar ved et oppdrag representerer forventet ankomsttid. Rundens
    # slutt er myk: sen ankomst er lov, men hvert minutt får en høy kostnad.
    for oppdrag_indeks, ett_oppdrag in enumerate(
        planleggingsoppdrag,
        start=1,
    ):
        intern_indeks = manager.NodeToIndex(oppdrag_indeks)
        ankomstvariabel = arbeidstid_dimensjon.CumulVar(intern_indeks)
        arbeidstid_dimensjon.SetCumulVarSoftUpperBound(
            intern_indeks,
            besoksrunde.sluttid,
            100,
        )

        if ett_oppdrag.kritisk_tidligste_start is not None:
            ankomstvariabel.SetRange(
                ett_oppdrag.kritisk_tidligste_start,
                ett_oppdrag.kritisk_seneste_start,
            )

    # Alle plassene i et fleransattoppdrag må ha nøyaktig samme ankomsttid.
    for nodegruppe in samtidige_nodegrupper:
        for node in nodegruppe[1:]:
            routing.solver().Add(
                arbeidstid_dimensjon.CumulVar(manager.NodeToIndex(node))
                == arbeidstid_dimensjon.CumulVar(
                    manager.NodeToIndex(nodegruppe[0])
                )
            )

    for ansatt_indeks in range(antall_ansatte):
        start_indeks = routing.Start(ansatt_indeks)
        slutt_indeks = routing.End(ansatt_indeks)
        arbeidstid_dimensjon.CumulVar(start_indeks).SetValue(
            besoksrunde.starttid
        )
        routing.AddVariableMinimizedByFinalizer(
            arbeidstid_dimensjon.CumulVar(slutt_indeks)
        )

    # Dette straffer en lang arbeidsrute. Sammen med kjørekostnaden over gir
    # det en avveining mellom kort total kjøring og jevnere arbeidsdager.
    arbeidstid_dimensjon.SetGlobalSpanCostCoefficient(10)

    sokeparametere = pywrapcp.DefaultRoutingSearchParameters()
    sokeparametere.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    sokeparametere.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    sokeparametere.time_limit.seconds = 5

    losning = routing.SolveWithParameters(sokeparametere)
    if losning is None:
        raise RuntimeError(
            "OR-Tools fant ingen gyldig plan. Kontroller tidsvinduer, "
            "kvalifikasjonskrav og antall ansatte."
        )

    return _bygg_ruter_fra_losning(
        ansatte,
        planleggingsoppdrag,
        kjoretider,
        stedsnavn,
        manager,
        routing,
        losning,
        arbeidstid_dimensjon,
        besoksrunde,
    )


def _bygg_ruter_fra_losning(
    ansatte: list[Ansatt],
    planleggingsoppdrag: list[Oppdrag],
    kjoretider: Kjoretidsmatrise,
    stedsnavn: list[str],
    manager: pywrapcp.RoutingIndexManager,
    routing: pywrapcp.RoutingModel,
    losning: pywrapcp.Assignment,
    arbeidstid_dimensjon: pywrapcp.RoutingDimension,
    besoksrunde: Besoksrunde,
) -> list[AnsattRute]:
    """Gjør OR-Tools-resultatet om til prosjektets enkle rutemodeller."""

    ruter: list[AnsattRute] = []

    for ansatt_indeks, ansatt in enumerate(ansatte):
        rute = AnsattRute(ansatt)
        indeks = routing.Start(ansatt_indeks)

        while not routing.IsEnd(indeks):
            neste_indeks = losning.Value(routing.NextVar(indeks))
            fra_node = manager.IndexToNode(indeks)
            til_node = manager.IndexToNode(neste_indeks)
            kjoretid = kjoretider[stedsnavn[fra_node]][stedsnavn[til_node]]

            rute.total_kjoretid += kjoretid

            if til_node == 0:
                # Siste etappe går fra siste oppdrag tilbake til depotet.
                rute.kjoretid_til_depot = kjoretid
                rute.navarende_sted = "Depot"
            else:
                neste_oppdrag = planleggingsoppdrag[til_node - 1]
                ankomst = losning.Value(
                    arbeidstid_dimensjon.CumulVar(neste_indeks)
                )
                avslutning = ankomst + neste_oppdrag.varighet
                rute.stopp.append((neste_oppdrag, kjoretid))
                rute.tidspunkter.append((ankomst, avslutning))
                rute.navarende_sted = neste_oppdrag.id

            indeks = neste_indeks

        rute.tilbake_pa_depot_tid = losning.Value(
            arbeidstid_dimensjon.CumulVar(routing.End(ansatt_indeks))
        )
        rute.total_arbeidstid = (
            rute.tilbake_pa_depot_tid - besoksrunde.starttid
        )
        ruter.append(rute)

    return ruter

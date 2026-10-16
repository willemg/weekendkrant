# Weekendkrant

Weekendkrant is een experimentele, grotendeels geautomatiseerde nieuwsredactie voor een persoonlijk weekendmagazine.

Het systeem is bewust opgesplitst in een reeks smalle rollen:

- **Sherlock** verzamelt nieuws, doet een eerste lichte triage en vat bronnen compact samen.
- **Ariadne** is volledig deterministisch en vlecht Sherlocks output tot thematische draden met een harde tokenlimiet.
- **Leonardo** maakt van die draden inhoudelijke syntheses en verhalen en schrijft compacte dossierstate.
- **Kuifje** is de toekomstige onderzoeksreporter voor expliciete missies van Leonardo.
- **Striktland** controleert of feitelijke claims door het aangeleverde bronmateriaal worden gedragen.
- **Minos** herschrijft alleen wanneer Striktland een probleem vindt en velt daarmee het eindoordeel.

De kernprincipes zijn:

1. webvergaring zoveel mogelijk uitvoeren binnen reeds inbegrepen ChatGPT-capaciteit;
2. deterministische verwerking tussen verzameling en dure modelcalls plaatsen;
3. intelligente modellen zo weinig mogelijk irrelevante tokens laten lezen;
4. feitelijke claims traceerbaar houden naar bronmateriaal;
5. kwaliteitscontrole eindig houden: geen oneindige regressielussen;
6. de hele keten auditeerbaar maken.

Zie de ontwerpdocumentatie:

- [Intelligente workers, rollen en gefaseerd migratieplan](docs/intelligent-worker-orchestration.md)
- [Architectuur](docs/architecture.md)
- [Rollen: Sherlock, Ariadne, Leonardo, Kuifje, Striktland en Minos](docs/roles.md)
- [Leonardo: geheugen, draden en deterministische regie](docs/leonardo-memory-and-orchestration.md)
- [Token- en kostenstrategie](docs/token-and-cost-strategy.md)
- [Audit trail en kwaliteitslabels](docs/audit-trail.md)
- [Technisch leerlog: incidenten en blijvende regels](docs/lessons-learned.md)
- [Redactionele principes](docs/editorial-principles.md)

## Huidige runtime

Het [ontwerpbesluit van 13 oktober 2026](docs/intelligent-worker-orchestration.md)
kiest generieke scheduled executors met één begrensde rol/job per activatie en
minstens uurlijk, mogelijk sneller lokaal materialiseren als doelrichting.
Generieke jobopslag (fase 3) en de MCP/control-plane (fase 4) zijn geïmplementeerd.
Fase 5 implementeert nu de minimale Sherlock-jobproductie, atomaire executorstart
en gefencete bron-/ficheadapters; zie [Sherlock-executor](docs/sherlock-executor.md).
De algemene/state-driven dispatcher volgt in fase 7. Productie-invoering en de
actieve schedulerinstructies zijn afzonderlijke stappen; de bestaande productie-
runtime wordt niet door een repositorywijziging omgeschakeld. De bestaande `daily` is
geschikt voor herhaalde starts; de productiecron draait sinds 16 oktober 2026 op
:15/:45. Empirische evaluatie van deze nieuwe halfuurcadans blijft open.

`Sherlock -> MCP ingress -> ingress_queue.pending -> Ariadne daily -> lokale draden -> ingress_queue.processed`

MCP/SQLite is de persistente ingressqueue. Pending items met `payload.date` tot en
met vandaag in `Europe/Brussels` blijven verwerkbaar totdat ze succesvol processed
zijn. De payloaddatum is provenance/ordening, geen eenmalig consumptievenster.
Een fout laat werk pending; de volgende geschikte run haalt het vanzelf in.
Geldige toekomstige fiches wachten. Een lege queue geeft success met nul draden.

Ariadne bundelt per **ISO-week + topic** en laat de open part over daggrenzen
groeien. Nieuwe fiches volgen `(payload.date, numerieke queue-ID)`; bestaande
bronnen blijven in hun opgeslagen volgorde. Overflow sluit de part definitief
en begint de volgende. Per week/topic is maximaal één part open.

Elke groei schrijft eerst een nieuw immutable revisiebestand; na commit mag de
geverifieerde vorige actieve fysieke kopie vervallen. Alle logische revisies
blijven exact reconstrueerbaar uit SQLite. Actieve, gesloten en offered inputfiles
blijven behouden; bestaande historische kopieën krijgen alleen een expliciete
dry-run/apply-cleanup. Zie [fase 6.5 en opslagbesparing](docs/revision-storage.md).
SQLite bewaart het
exacte bronarchief, revisiehashes, tokenmetingen, bronposities en de actieve
revisie. De korte eindtransactie registreert alles samen met queue-status.
`database.py` en de genummerde migraties in `migrations/` beheren het volledige
SQLite-schema; zie [databasebeheer](docs/database.md). Bestaande rijen en
historische dagbestanden blijven behouden. Nieuwe items gebruiken uitsluitend
het partmodel; het eerste item maakt part 1/revision 1.
Zie [runtime en crashgedrag](docs/daily-runtime.md).
Voor de verplichte systeemtest na ketenwijzigingen en de aanvullende deployment
smoke: [testopdracht en operationele gate](docs/daily-runtime.md#systeemtest-en-operationele-gate).

`daily` is de enige operationele Ariadne-taak. Er zijn geen Git-operaties,
weekbranches, beheerde weekworktree, weekrapport of automatische retentie nodig.
Het lokale runtime-slot staat buiten de applicatierepository. Historische Git-data
blijft behouden; bestaande SQLite-rijen worden niet opgeruimd en er is geen
automatische `VACUUM`. Het lokale offer/seal-mechanisme is geïmplementeerd:
`PartStore.offer(part_id, revision)` registreert exact de actieve revisie en sluit
de part atomisch; een identieke retry retourneert hetzelfde immutable offer.
Ook overflow-gesloten parts zijn offerbaar. `daily` biedt ze automatisch aan;
open parts volgen na 25 minuten rust zonder pending week/topic-input of running
Sherlock-run, met volledige tijdprovenance. Zie het
[aanbiedcontract](docs/daily-runtime.md#automatisch-lokaal-aanbiedmoment-fase-6). Dit bewijst geen ontvangst door een
model. Nieuwe fiches gaan naar de volgende part. Dossiers, rolling state, Kuifje, modelcalls,
budgetten en eindredactionele planning volgen in afzonderlijke stappen.

De Quick Tunnel-component publiceert de actuele endpoint-URL via
`config/ingress-endpoint.json` op GitHub. De MCP-plugin leest die discoverypointer.
Zie [ingress-runtime](docs/ingress-runtime.md); tunnel/plugin/Sherlock veranderen
niet door deze cleanup.

Architecturaal grondmotief: **bibib lean and mean**. Op bibib komen alleen
componenten en dependencies die daar werkelijk nodig zijn in productie.
Ontwikkel-, build- en testdependencies van externe lagen blijven bij hun eigen
laag; de MCP/Sites-plugin wordt afzonderlijk ontwikkeld en getest.

## Installatie en uitvoering

Python 3.9 of nieuwer en de tokenizer uit `requirements.txt` zijn vereist.
`./start_tests.sh` en alle Python unit-, integratie- en systeemtests op bibib
zijn volledig Node-vrij. Node.js is uitsluitend vereist voor de afzonderlijke
MCP/Sites-plugin-developmenttests en build; zie
[plugin-testvereisten](plugin/weekendkrant_ingress/README.md#lokaal-testen-en-bouwen).
De installatie staat onder `/home/weekendkrant/app`:

```bash
cd /home/weekendkrant/app
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./start_tests.sh
./start_ariadne.sh daily
```

De wrappers gebruiken rechtstreeks de venv-interpreter; activeren is niet nodig.
JSON verschijnt op stdout, logging in `/home/weekendkrant/logs/ariadne.log`
(1 MiB, vier backups). DB, draden en runtime-lock staan buiten de applicatierepository.
Zie [preflight en croncontract](docs/daily-runtime.md#installeren-en-handmatig-controleren-op-bibib).

Verwijder na merge handmatig de obsolete zondagregel op bibib:

```cron
0 22 * * 0 /home/weekendkrant/app/start_ariadne.sh prepare-week --next-week >/dev/null
```

De op 16 oktober 2026 handmatig ingevoerde productieregel (één `daily`-regel):

```cron
15,45 * * * * /home/weekendkrant/app/start_ariadne.sh daily >/dev/null
```

De code wijzigt geen crontab en verwijdert geen bestaande worktrees of branches.
Zie [invoering en rollback](docs/daily-runtime.md#croncontract-na-merge).

## Database

Zie [docs/database.md](docs/database.md) voor het canonieke SQLite-schema, scratch-build en migraties.

Generieke jobopslag (fase 3) en MCP/control-plane (fase 4), Sherlock-adapter (fase 5, schema 9), met het
conservatieve claim-/herstel- en operation-retrycontract
staan in [docs/jobs.md](docs/jobs.md) en [Sherlock-executor](docs/sherlock-executor.md);
operationele invoering volgt afzonderlijk.

Tests: `./start_tests.sh` kiest [impacttests](docs/test-fast-track.md);
`./start_tests.sh --all` draait de volledige suite.
De eerste [Leonardo-backendslice](docs/leonardo-state.md) gebruikt schema 11.

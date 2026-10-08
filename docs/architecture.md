# Architectuur

## Huidige productiearchitectuur

`Sherlock -> MCP ingress -> ingress_queue.pending -> Ariadne daily -> lokale draden -> ingress_queue.processed`

Sherlock levert bronfiches via de Weekendkrant Ingress MCP-plugin aan de HTTPS
API op bibib. De API bindt lokaal op `127.0.0.1:8000`, authenticeert met een bearer
token en retourneert HTTP 201 pas na persistente ontvangst in SQLite. Ariadne
valideert het strikte schema-version-1-contract en vlecht deterministisch.
Zie [ingress-runtime](ingress-runtime.md) en [dagelijkse runtime](daily-runtime.md).

De persistente queue is het retrymechanisme. `daily` selecteert pending fiches tot
en met vandaag in `Europe/Brussels`, inclusief achterstand. Toekomstige fiches
blijven pending. De payloaddatum is provenance en ordening; geen afgesloten
consumptievenster. Succesvolle dagrecords blokkeren nooit nieuw pending werk.

## Lokale runtime

| Pad | Functie |
| --- | --- |
| `/home/weekendkrant/app/` | Applicatiecode, startscripts, tests en `.venv`. |
| `/home/weekendkrant/weekendkrant.sqlite3` | Persistente ingressqueue en legacy verwerkingsprovenance. |
| `/home/weekendkrant/draden/` | Afgeleide draadbestanden per oorspronkelijke datum/topic. |
| `/home/weekendkrant/ariadne.lock` | Niet-blokkerend lokaal één-consument-slot, onafhankelijk van Git. |
| `/home/weekendkrant/logs/ariadne.log` | Runtimelogging. |
| `/home/weekendkrant/.cache/tiktoken/` | Encodingcache voor de vastgelegde tokenizer. |

Operationele DB, output en lock staan buiten de applicatierepository.
`daily` gebruikt geen Git-commando's en vereist geen Git-repository-operaties.
Een snapshot wordt zonder write-lock gevalideerd, getokeniseerd en naar files
geschreven. Een korte finale transactie controleert de snapshot opnieuw en
registreert provenance en processed-status samen. Producer en consument gebruiken
aparte SQLite-connections; toevoegingen tijdens weven of schrijven wachten niet
op een langdurige consumenten-write-lock.

Nieuwe output groepeert per oorspronkelijke datum/topic en numerieke queue-ID.
Het volgende legacy-partnummer volgt uit gecommitte `threads`-provenance.
Late fiches krijgen volgende parts; succesvolle files blijven intact. Retry van
dezelfde snapshot hergebruikt dezelfde nog niet geregistreerde paden en bytes.

## GitHub en discovery

GitHub bewaart code en ontwerpdocumentatie en publiceert de discoverypointer.
Het is geen fichequeue en geen onderdeel van Ariadnes verwerking.

`cloudflared Quick Tunnel -> actuele URL -> config/ingress-endpoint.json op GitHub -> MCP-plugin`

De tunnelpublisher gebruikt een zelfstandige tijdelijke shallow clone met
bestaande GitHub SSH-authenticatie, buiten de app. Alleen de discoverypointer
wordt gepubliceerd. Deze cleanup wijzigt geen tunnel-, API- of MCP-pluginlogica.
Historische ingressbranches en worktrees worden niet automatisch verwijderd.

## Cron en retentie

`daily` is de enige huidige Ariadne-taak, dagelijks om 10:00 Belgische tijd.
Na merge moet de zondagse `prepare-week --next-week`-cronregel handmatig weg;
zie het exacte [croncontract](daily-runtime.md#croncontract-na-merge).
Er is geen wekelijkse volledigheidscontrole, automatische achtwekenretentie of
`VACUUM`. Een ontbrekend dagrecord is op zichzelf geen fout. Pending is werk;
processed is succesvol geconsumeerd. Bestaande SQLite-data blijft behouden.

`days`, `attempts`, `threads` en `sources` blijven voorlopig legacy audit en
provenance; `days.status` bestuurt de queue niet. Een nieuw bewaarbeleid volgt
apart met het dossier-/partmodel.

## Logging

Centrale Python-logging schrijft INFO en hoger naar
`/home/weekendkrant/logs/ariadne.log`. DEBUG kan expliciet worden aangezet.
`RotatingFileHandler` roteert bij 1 MiB met vier backups, circa 5 MiB totaal.
Geen lifecyclelogging op stdout; daar staat het gestructureerde JSON-resultaat.
De uitvoerende gebruiker moet de logmap kunnen aanmaken of beschrijven.
Logginginitialisatiefouten stoppen de CLI met exitcode 1 en een stderr-diagnose.

## Volgende stap: doelontwerp uit PR #16

[Leonardo-geheugen en regie](leonardo-memory-and-orchestration.md) blijft het
doelontwerp. Het persistente week/topic-partmodel met immutable revisies,
rolling state, callbuilder, kostenadministratie en Kuifje-missies zijn nog niet
geïmplementeerd. Deze cleanup houdt de legacy-datum/topic-output en introduceert
geen nieuw part-/revisieschema of modelcalls.

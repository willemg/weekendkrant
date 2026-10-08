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
| `/home/weekendkrant/weekendkrant.sqlite3` | Ingressqueue, bronarchief, partrevisies en historische legacyprovenance. |
| `/home/weekendkrant/draden/` | Immutable revisiebestanden per ISO-week/topic/part. |
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

Nieuwe output groepeert per ISO-week + topic. De open part groeit over dagen
via nieuwe immutable revisies. Nieuwe bronnen volgen `(payload.date, numerieke
queue-ID)` en worden achter bestaande bronmembership toegevoegd. Overflow sluit
de part definitief. Een partial unique index bewaakt maximaal één open part.

`parts.py` bevat de kleine expliciete SQLite-opslaglaag en de mechanische planner.
`PRAGMA user_version=1` voegt `parts`, `part_revisions`, `source_archive` en
`revision_sources` toe zonder legacyrows te transformeren. Exacte bronbytes
blijven onafhankelijk van de transportqueue bestaan. De finale transactie
controleert ook de geplande partstaat en verschuift de actieve revisie samen
met provenance en processed-status. Zie [partschema](audit-trail.md#partschema-versie-1).

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

`days`, `threads` en `sources` blijven historische legacyprovenance zonder nieuwe
partwrites. `attempts` bewaart runtimefouten; geen dagstatus bestuurt de queue.
Een nieuw bewaarbeleid volgt apart.

## Logging

Centrale Python-logging schrijft INFO en hoger naar
`/home/weekendkrant/logs/ariadne.log`. DEBUG kan expliciet worden aangezet.
`RotatingFileHandler` roteert bij 1 MiB met vier backups, circa 5 MiB totaal.
Geen lifecyclelogging op stdout; daar staat het gestructureerde JSON-resultaat.
De uitvoerende gebruiker moet de logmap kunnen aanmaken of beschrijven.
Logginginitialisatiefouten stoppen de CLI met exitcode 1 en een stderr-diagnose.

## Geïmplementeerd en gepland

Geïmplementeerd: persistente backlog, cross-day week/topic-parts, open parts,
immutable revisions, exact bronarchief, deterministische overflow en crashsafe
registratie. Legacy-dagbestanden worden niet retroactief gemigreerd.

[Leonardo-geheugen en regie](leonardo-memory-and-orchestration.md) beschrijft ook
het toekomstige ontwerp. Aanbieding en offered-lifecycle, dossiers, rolling
state, Kuifje, modelcalls, callbudgetten, aanbiedplanning en eindredactionele
weekdeadline zijn nog niet geïmplementeerd.

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

## Grondmotief: bibib lean and mean

Bibib blijft een compacte productiehost: iedere geïnstalleerde component en
dependency moet nodig zijn voor werk dat daar in productie werkelijk draait.
Dat omvat de Python-backend, SQLite, deterministische Ariadne-verwerking en de
bestaande tunnel/discoverycomponenten met hun eigen productievereisten.
Een gezamenlijke repository maakt bibib niet tot ontwikkel- of buildhost voor
alle onderdelen van Weekendkrant.

Ontwikkel-, build- en testdependencies van externe lagen blijven bij die laag.
De JavaScript MCP-bridge draait op ChatGPT Sites; Node.js hoort uitsluitend bij
plugin-development en pluginchecks. De gewone Python unit-, integratie- en
systeemtests op bibib gebruiken de lokale productiecomponenten en blijven volledig
Node-vrij, inclusief `./start_tests.sh` en de Python-systeemgate.

De expliciete bridge → HTTP → SQLite-developmenttest staat onder de plugin-tests
in een afzonderlijke ontwikkelomgeving, buiten de Python-discovery. Het werkelijk
gepubliceerde Sites → tunnel → backend-pad wordt apart bewezen door de bestaande
deployment-smoke. Zo blijft lokale testdekking behouden zonder dependencies van
de externe laag op bibib te installeren. Zie [testlagen en bewijsgrenzen](jobs.md#testlagen-en-bewijsgrenzen)
en [pluginchecks](../plugin/weekendkrant_ingress/README.md#lokaal-testen-en-bouwen).

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

`database.py` en de genummerde migraties in `migrations/` zijn eigenaar van het
volledige SQLite-schema en de migratieketen. Zie [databasebeheer](database.md)
voor het canonieke schema, de actuele versie en migratiedetails.
`parts.py` bevat de part-opslaglogica en de mechanische planner, maar beheert
geen eigen DDL; ook `daily.py` en `ingress_queue.py` gebruiken de centrale migratiecode.

Exacte bronbytes blijven onafhankelijk van de transportqueue bestaan.
De finale transactie controleert ook de geplande partstaat en verschuift de
actieve revisie samen met provenance en processed-status.
Zie [partmodel en provenance](audit-trail.md#partmodel-en-provenance).

## Afzonderlijke lokale CI

De optionele fast-tracktrigger registreert een concrete SHA in externe
`/home/weekendkrant/ci`-state. Een uurlijkse lokale runner test die SHA via de
canonieke volledige Python-suite in een verse wegwerpclone, met een eigen
niet-blokkerende lock. Atomische resultaatregistratie en request-CAS behouden
ondertussen nieuw pending werk. De live `/home/weekendkrant/app` wordt door CI
nooit als worktree of clonesource gebruikt. Operationele JSON-state, compacte SQLite-rapportage, één failurecheckout met log,
runnerinstallatie en gedeelde CI-venv staan buiten de applicatiecheckout.
Dit is lokaal geïmplementeerd; productieactivering volgt na merge. Zie
[CI-contract, crashsemantiek en runbook](ci.md).

## GitHub en discovery

`willemg/weekendkrant` is de enige source of truth voor alle niet-geheime code
en ontwerpdocumentatie en publiceert de discoverypointer. Het is geen fichequeue
en geen onderdeel van Ariadnes verwerking.

ChatGPT Sites is de stabiele MCP-runtime/deploymentlaag; de Quick Tunnel naar
bibib mag dankzij discovery een dynamische URL behouden. Plugin-deployment
bestaat momenteel uit synchronisatie van één gemergede GitHub-commit naar Sites,
gevolgd door afzonderlijke publicatie. Ontwikkeling en tests gebeuren bij de
GitHub-bron. Zie [pluginbronbeheer en deployment](plugin-deployment.md) voor de
canonieke werkwijze en de motivatie voor deze twee stappen.

`cloudflared Quick Tunnel -> actuele URL -> config/ingress-endpoint.json op GitHub -> MCP-plugin`

De tunnelpublisher gebruikt een zelfstandige tijdelijke shallow clone met
bestaande GitHub SSH-authenticatie, buiten de app. Alleen de discoverypointer
wordt gepubliceerd. Deze cleanup wijzigt geen tunnel-, API- of MCP-pluginlogica.
Historische ingressbranches en worktrees worden niet automatisch verwijderd.

## Cron en retentie

`daily` is de enige huidige Ariadne-taak en ondersteunt herhaalde runs op dezelfde
dag. Het voorlopige lokale croncontract is iedere 15 minuten; productie-invoering
gebeurt na merge handmatig en is geen gevolg van alleen een repository-update.
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
registratie en expliciete lokale offer/seal-registratie. Legacy-dagbestanden worden niet retroactief gemigreerd.

Ook geïmplementeerd: de generieke job-/attemptopslag van fase 3 en de expliciete
MCP/control-plane van fase 4, met claimvalidatie en persistente operatieretries.
Dit is geen bewijs van productie-invoering of geïntegreerde jobuitvoering.
Fase 5 implementeert de eerste Sherlock-jobproductie/topicrotatie, atomaire
executorstart en gefencete bron-/fichewrites; zie [Sherlock-executor](sherlock-executor.md).
De actieve scheduler en externe deployment worden afzonderlijk ingevoerd.
De algemene/state-driven dispatcher en bredere policy volgen in fase 7.
Zie [het canonieke board](intelligent-worker-orchestration.md) en [jobprotocol](jobs.md).

[Leonardo-geheugen en regie](leonardo-memory-and-orchestration.md) beschrijft ook
het toekomstige ontwerp. Een offer bevriest de actieve revisie en sluit de part
in één korte transactie, zonder files te wijzigen of een model aan te roepen.
Een gesloten part zonder offer is ook nog offerbaar. Dossiers, rolling
state, Kuifje, modelcalls, callbudgetten, aanbiedplanning en eindredactionele
weekdeadline zijn nog niet geïmplementeerd.


Fase 9.5: de scheduled executor gebruikt het minimale canonieke
`executor/instructions.md`. Bibib beheert bootstrap-identiteit, tijd en interne
operaties. Start geeft alleen executor_id; jobophaling leest de bestaande
immutable binding. Finish/abandon vereisen geen modelgegenereerde operatie-ID.
Er is geen nieuw schema, sessiemodel of scheduler. Zie [dispatcher](dispatcher.md).


Fase 11: Leonardo's `processed_refs` blijft de authoritative grens van verwerkte
immutable partrevisions. Itemvelden `refs`, `support` en `counterevidence` mogen
ook `queue:<id>` noemen, uitsluitend wanneer de bestaande immutable
`revision_sources`-membership die fiche aan een van die exacte processed revisions
koppelt. Dit verfijnt inputprovenance zonder extra inputmechanisme of mappingopslag.
De server valideert deze grens atomair bij statefinish en respecteert het
bevroren outputcontract van de job. Zie [Leonardo-state](leonardo-state.md).


## Fase 12: gesloten onderzoekslus

Bestaande Leonardo-state → expliciete reevaluation zonder nieuwe parts → aparte
immutable Kuifje-missie/assignment → generieke Kuifje-job → bestaande fiche-ingress
→ Ariadne → immutable partrevision → latere gewone Leonardo-run.
Missies horen nooit in Leonardo-state. Ariadne bezit één canonieke tokenizer in
ariadne_tokens.py, gedeeld door actuele verwerking en agents. Historische
WEEKENDKRANT-PART-1-reconstructie behoudt haar onafhankelijke frozen v1-tokenaudit.
Ook lege of mislukte Kuifje-onderzoeken kunnen expliciet als aanvullende frozen
Leonardo-assignmentcontext worden geselecteerd, zonder synthetische bronnen.
Zie [opslag, fencing, tokenaudit en grenzen](phase-12-kuifje.md).

# Expliciete fast-track

`./start_tests.sh` voert altijd precies de geversioneerde selectie in
[`tests/fast_track.txt`](../tests/fast_track.txt) uit, ook op een schone gepullde
main. Er is geen Git-diff, merge-base, AST-analyse of automatische verbreding.
Branch, Git-status en zelfs de aanwezigheid van Git veranderen de selectie niet.
De lijst representeert bewust de regressieset van de laatst gemergede
functionele wijziging. De volgende functionele PR beoordeelt en actualiseert hem
voor zijn eigen impact; het is geen permanent groeiende verzameling smoke-tests.
De verplichte onderhoudsregel staat in het [technisch leerlog](lessons-learned.md)
en wordt vóór ontwikkelwerk aangewezen door [AGENTS.md](../AGENTS.md).

## Normale ontwikkel- en PR-validatiecyclus

Gebruik tijdens normale ontwikkeling, TDD en PR-validatie uitsluitend
`./start_tests.sh`. De fast-track is tevens de normale post-pull/deploymenttest.
Draai `./start_tests.sh --all` niet standaard vóór review of merge; een volledige
suite is geen normale PR-gate. Voer hem alleen uit als de opdracht dit expliciet
vraagt of als er een concrete uitzonderlijke technische reden bestaat. Vermeld
bij zo'n uitzondering waarom de volledige suite nodig was. De beschikbaarheid
van `--all` betekent niet dat iedere PR hem moet uitvoeren.

## Lijstformaat en fouten

Eén unittest-module, klasse of afzonderlijke test per regel, bijvoorbeeld:

```text
test_leonardo
test_jobs.JobTests.test_identity_attempt_and_exact_retries
```

Gebruik lokale modules uit `tests/test_*.py`, zonder `tests.`-prefix of `.py`.
Blanco regels en `#`-commentaar zijn toegestaan. Een module/klasse betekent al
zijn tests; een methode betekent uitsluitend die test. Iedere selectie wordt
getoond, gevolgd door het aantal modules en werkelijk geladen tests.

De runner valideert de volledige lijst vóór hij tests uitvoert. Een ontbrekende
of lege lijst, ongeldige/verwijderde naam, importfout, selectie zonder tests of
dubbele/overlappende tests faalt hard. Er is geen stille fallback naar nul tests
of naar de volledige suite. Onbekende CLI-argumenten falen eveneens.

`./start_tests.sh --all` gebruikt de volledige unittest-discovery in `tests/`,
onafhankelijk van de fast-tracklijst, en faalt ook als er geen tests bestaan.
Tijdens ontwikkeling blijft dit uitsluitend de expliciete of technisch
gemotiveerde uitzondering op de normale fast-trackcyclus hierboven. De
[afzonderlijke volledige CI-runtime](ci.md) gebruikt dit pad bewust vanuit een
verse tijdelijke clone van precies de pending SHA; dat maakt de volledige suite
nog geen verplichte lokale PR-gate. Het shellscript werkt vanuit zijn eigen checkout en
gebruikt een expliciete `WEEKENDKRANT_TEST_PYTHON` wanneer ingesteld, anders de
lokale `.venv/bin/python` als die bestaat, anders `python3`. Zo kan een tijdelijke
CI-clone de stabiele externe CI-venv gebruiken.

## Initiële regressieset van PR #56

De lijst is inhoudelijk gezaaid met fase 8 en de runnerwijziging, niet met de
oude automatische full-suite-fallback. De selectie omvat:

| Selectie | Reden |
| --- | --- |
| `test_leonardo` | Alle nieuwe state/job-, schema-11-, HTTP-, no-op- en phantom-outputregressies |
| `test_database` | Centrale migratieketen, behoud data, rollback en schema 11 |
| `test_dispatcher` | Gedeelde ready-first dispatcher, admission, snapshots en recovery |
| `test_job_control` | Gedeelde finish/fencing/receipts en exacte herhalingen |
| `test_job_http` | Echte HTTP-control-plane en Sherlock-compatibiliteit |
| `test_sherlock_executor` | Sherlock naast de Leonardo-adapter; claims, recovery en gefencete effecten |
| `test_system_e2e` | Echte HTTP/queue/Ariadne/parts-keten, inclusief generieke Sherlock-jobs |
| `test_test_runner` | Expliciete lijst, CLI, foute entries, nul tests en schone main |
| Drie benoemde `test_jobs`-tests | Exacte finish-retries, expiry-fencing en atomaire finishrollback |
| Eén benoemde `test_revision_storage`-test | Historische Leonardo-bronrevisies blijven exact reconstrueerbaar |
| Eén benoemde `test_offers`-test | Offers worden nog niet automatisch Leonardo-jobs |

Alleen Python-tests horen in deze lijst, zodat bibib Node-vrij blijft. De echte
Leonardo-HTTP/backendregressies zitten wel in de fast-track. Aanvullende
MCP/bridgechecks blijven expliciet in de pluginontwikkelomgeving:

```bash
npm --prefix plugin/weekendkrant_ingress test
npm --prefix plugin/weekendkrant_ingress run test:backend
```

De bridge-backendtest dekt ook Leonardo succeeded A/B/C, failed, uncertain en
abandon via echte MCP → HTTP → SQLite. Hij wordt niet overgeslagen op basis van
beschikbare dependencies binnen de fast-track; hij heeft een afzonderlijk
laagcontract en wordt daar uitgevoerd. De deployment-smoke blijft eveneens een
afzonderlijke operationele controle.

## Regressieset fase 8.5

De nieuwe lijst vervangt bewust de fase-8/runnerselectie: `test_role_contracts`
(8 nieuwe tests voor exacte UTF-8-bytes/hashes, bounds, snapshotversies,
recovery/replay en de executorgrens), `test_dispatcher` (lazy preparation en
ready-first), `test_sherlock_executor` (claims, snapshotopslag en recovery),
`test_leonardo` (state, provenance, token-/bytegrenzen, CAS, fencing en finish),
`test_job_control` (gedeelde finish/receipts) en `test_system_e2e` (lokale echte
HTTP/queue/Ariadne-keten). Geen runner- of schemawijziging, dus geen automatische
overname van de eerdere runner-/migratiechecks. Validatie: uitsluitend
`./start_tests.sh`, 69 tests groen in 20,293 seconden; geen `--all` of deployment.


## Regressieset fase 9.5

De vorige fase-9-selectie is vervangen door bootstrap, dispatcher, slotting,
job-control/HTTP, Sherlock, Leonardo, contractsnapshots en de lokale systeemketen.
Deze negen modules raken precies het gewijzigde scheduled transport en zijn
gedeelde state/fencing-invarianten. Operatorvoorbereiding, offers, migraties en
de testrunner worden niet automatisch overgenomen: die implementaties wijzigen
niet. De default blijft Node-vrij. Alleen in de pluginontwikkelomgeving draait
`./start_tests.sh --plugin` expliciet de JavaScript-contracttests en bridge/backend-
keten; dit is geen volledige Python-suite en vereist geen Node op bibib.

## Regressieset fase 9.6

De selectie is bewust vervangen door acht modules: `test_leonardo_recall`
(nieuwe autorisatie, herlezing, audit, grenzen, concurrente retries en migratie),
`test_leonardo` (snapshot/state/finish), `test_database` (centrale migratieketen),
`test_leonardo_operator` (volledige en compacte inspectie), `test_role_contracts`
(immutable contracten), `test_job_control` (gedeelde finish/fencing),
`test_executor_bootstrap` (ongewijzigd generiek jobtransport) en `test_system_e2e`
(bestaande Sherlock → ingress → Ariadne-keten). De ongewijzigde slotting- en
selectiepolicytests worden niet uit de vorige lijst overgenomen. Dit is de
kleinste gekozen impactset op moduleniveau; Node blijft buiten de default.
`./start_tests.sh --plugin` valideert apart de publieke toolmetadata, transport-
contracten en echte MCP → HTTP → SQLite-recall plus generieke finish.


## Fase 10: snelle gate en asynchrone volledige CI

De nieuwe selectie bevat uitsluitend `test_ci_runner` (nieuwe state-, clone-,
crash-, locking-, notificatie- en triggerregressies) en `test_test_runner`
(geraakt canoniek testpad en bestaande selectie-/CLI-regressies). De vorige
Leonardo-/backendselectie wordt bewust volledig vervangen; die code wijzigt niet.

Met `WEEKENDKRANT_CI_STATE` markeert alleen een succesvolle schone fast-track
zijn exacte HEAD voor volledige CI. Zonder die configuratie blijven selectie
en gedrag onafhankelijk van Git; dirty development blijft mogelijk. De trigger
haalt niets op en vereist geen actieve worker. `--all` en pluginchecks triggeren
niet opnieuw. Zie [het canonieke CI-document](ci.md) voor de precieze
voor-/nacontroles, foutsemantiek, coalescing en productieactivering.

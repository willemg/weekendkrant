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
Dit blijft de expliciete volledige regressietest, niet de normale
post-pull/deploymenttest. Het shellscript werkt vanuit zijn eigen checkout en
gebruikt de lokale `.venv/bin/python` als die bestaat, anders `python3`.

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

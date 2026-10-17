# Lokale volledige CI (fase 10)

De volledige Python-suite is te traag voor iedere ontwikkeliteratie of pull.
`./start_tests.sh` blijft de synchrone fast-trackgate uit de geversioneerde lijst.
Een optionele lokale trigger registreert na een geslaagde, schone fast-track de
exacte HEAD voor een afzonderlijke volledige CI-run. Groen in de fast-track is
geen bewijs dat de volledige suite groen is.

De CI is een lokaal cronproces, zonder daemon, dispatcher of externe CI-provider.
Een aparte kleine SQLite-rapportdatabase bewaart uitsluitend historische
resultaten. De implementatie en gerichte tests zijn beschikbaar; productiecron,
externe venv en eerste echte volledige-suitebewijs worden **na merge** ingevoerd.
Geen lokale fixturetest vervangt dat runtimebewijs.

## Harde grenzen

- `/home/weekendkrant/app` blijft uitsluitend de applicatie-/deploymentcheckout.
  De CI clonet vanaf GitHub en voert daar nooit pull/reset/clean/checkout uit.
  Ook als lokale clonesource wordt dat pad geweigerd, inclusief symlinkaliases.
- Iedere run gebruikt een nieuwe `ci/work/run-*/repo`, met `git clone
  --no-checkout --no-local`, detached checkout van de volledige SHA en een
  afzonderlijke HEAD-verificatie. Er is geen herbruikbare CI-working tree.
- Alleen in die nieuwe clone draait `bash ./start_tests.sh --all`. Deze bestaande
  canonieke entrypoint ontdekt uitsluitend de Python-suite. Node/pluginchecks
  blijven bij de Sites-/pluginlaag; bibib blijft lean and mean.
- Git-argumenten zijn subprocesslijsten; geen state bevat uitvoerbare shelltekst.
  Geërfde `GIT_*`-variabelen kunnen Git niet naar een andere working tree/index
  omleiden. Clone-/checkouthooks worden voor deze commando's uitgeschakeld.
- State en work moeten buiten elke Git-checkout staan. Het resolved workpad moet
  een directe child van de eigen statedirectory zijn. Cleanup volgt geen
  orphan-symlinks en verwijdert uitsluitend de eigen `work/run-*`-prefix.

Dit is checkoutisolatie, geen sandbox voor willekeurige onbetrouwbare code:
zoals de bestaande lokale tests draait de geselecteerde vertrouwde repositorycode
onder de Unix-rechten van de uitvoerende gebruiker.

## Triggercontract

Zonder `WEEKENDKRANT_CI_STATE` verandert het normale testpad niet en schrijft het
geen CI-state. Met die variabele legt `test_runner.py` vóór testuitvoering een
schone HEAD vast en controleert na succes opnieuw dat HEAD en working tree niet
gewijzigd zijn. Pas dan wordt gemarkeerd. Untracked files tellen als vuil;
Git-ignored `.venv` en caches tellen niet mee.

Een vuile/niet-Git-checkout krijgt vooraf een expliciete `CI niet gemarkeerd`-
diagnose en mag zijn gewone fast-track blijven draaien. Een mislukte fast-track,
ongeldige selectie, `--all` of pluginrun markeert nooit. Een statewritefout of
checkoutwijziging tijdens een aanvankelijk schone run geeft na geslaagde tests
exitcode 2: de trigger is dan aantoonbaar niet bevestigd.

De trigger gebruikt alleen lokale Git-reads en korte statewrites; geen pull,
netwerkcall of workeradmission. Deployment blijft expliciet `git pull --ff-only`
gevolgd door de snelle test. Een al draaiende volledige suite vertraagt de
fast-track niet: de lange runnerlock en korte statelock zijn verschillende locks.

Dezelfde pending SHA opnieuw markeren bewaart dezelfde requestidentiteit.
Een reeds succesvol volledig geteste SHA zonder pending werk wordt niet opnieuw
ingepland. Nieuwe marks coalescen naar de laatste SHA. De automatische
checkouttrigger controleert Git-ancestry onder de statelock: een vertraagde
oudere trigger vervangt geen nieuwere SHA. Ontbrekende ancestry of divergerende
branches falen zichtbaar; een bewuste operator kan `mark --force` gebruiken.
De directe `mark --sha`-CLI is een expliciete operatorselectie en vereist geen
checkout of voorafgaande fast-track; gebruik hem dus bewust.

## Drie verantwoordelijkheden en resultaatbewaring

Alles staat onder `/home/weekendkrant/ci`, buiten de applicatiecheckout en met
private rechten voor `weekendkrant`.

| Pad | Verantwoordelijkheid |
| --- | --- |
| `state.json` | Pending/request-identiteit, actuele/laatste operationele status en minimale failuremetadata voor retry/notificatiededuplicatie. Geen logs of historiek. |
| `report.sqlite3` | Compacte historische resultaten, één rij per afgeronde logische request. Geen scheduler, pending, admission of lockbeheer. |
| `failure/repo`, `failure/test.log` | Maximaal één actuele debugcheckout met volledige uitvoer. Bij clone-/checkoutfailure kan de repo onvolledig/afwezig zijn; de log verklaart de infrastructuurfout. |
| `failure/result.json` | Kleine metadata-identiteit van dat artifact, geen tweede logkopie. |
| `work/run-*` | Verse actieve clone, streaming `test.log` en completionmetadata; bij groen geheel verwijderd. |
| `completion.json` | Eén klein duurzaam afrondingsreceipt voor crashherstel tussen filesystem, rapportage en state-CAS; verdwijnt na verwerking. |
| `failure.previous` | Alleen tijdens failure-safe vervanging, nooit reguliere historiek; na herstel/commit verwijderd. |
| `state.lock`, `runner.lock` | Korte read-modify-write-lock en afzonderlijke niet-blokkerende runnerlock. |
| `.state-*` | Tijdelijke atomaire writes; orphancleanup onder statelock. |
| `bin/`, `venv/`, `env` | Runnerinstallatie, externe Pythonomgeving en private operatorconfiguratie. |

**Succesvolle volledige CI is auditmetadata, geen debugartifact.** De eigen
clone, testlog en metadatafile verdwijnen volledig; SQLite houdt alleen SHA,
requestidentiteit, `succeeded`, start/eindtijd, duur en exitcode 0 bij. De
`artifact_path` is NULL. Er blijft geen successlog, `current.log` of groene
checkout achter. Operationele state bevat hoogstens de laatste compacte uitkomst.

**Bij rood is de exacte checkout plus output onderdeel van het
onderzoeksmateriaal.** De verse run-directory wordt naar het vaste `failure/`
verplaatst, inclusief de daadwerkelijk gebruikte repo en `test.log`. Bij een
gewone testfailure blijft HEAD op de geteste SHA; de working tree blijft zoals
zij faalde, zonder reset/clean. Bij infrastructuurfailure kan clone/checkout zelf
mislukt zijn: er wordt geen fictieve geldige checkout gereconstrueerd.

De volledige gecombineerde stdout/stderr streamt direct naar de logfile, samen
met command-/infrastructuurdiagnose. Er is een harde **64 MiB** veiligheidsgrens
per run (plus één korte limietmelding): bij overschrijding wordt de actieve
commandoprocesgroep gestopt, de run faalt met exitcode 2 en de log vermeldt expliciet dat de
uitvoer incompleet is. Dit is een runaway-outputnoodrem, geen 128-KiB-tail of
normale truncatie. Geen logbytes in JSON-state of SQLite.

Een nieuwe failure vervangt het vorige zware artifact pas wanneer de nieuwe
run-directory gereed is. Beide historische DB-rows blijven bestaan; de oude
`artifact_path` wordt NULL wanneer het artifact vervangen wordt. Een succes
verwijdert uitsluitend zijn eigen run-directory en behoudt de eerdere failure
voor onderzoek. `clear-failure` verwijdert bewust alleen het zware debugartifact
en maakt bijbehorende DB-verwijzingen NULL, zonder historische rows te wissen.
Het aantal zware bewaarde artifacts groeit dus niet mee met het aantal runs;
tijdens vervanging kunnen kort oud en nieuw naast elkaar bestaan.

## Rapportdatabase en idempotentie

`ci_runs` bevat `id`, `sha`, unieke `request_id`, `status`, `started_at`,
`finished_at`, `duration_seconds`, `exitcode` en nullable `artifact_path`.
Alleen afgeronde `succeeded`/`failed`-runs krijgen een row; geen logs, repoarchief
of schedulerstate. Tijden zijn UTC met offset; duur is de niet-negatieve gemeten
UTC-tijdsdelta. Een handmatige rerun heeft bewust een nieuwe requestidentiteit.

SQLite gebruikt gewone lokale transacties. Dezelfde completion opnieuw
registreren verandert geen historische metadata en maakt geen tweede row.
Een conflicterende uitkomst voor dezelfde request wordt hard geweigerd.
Rapportage is onafhankelijk van scheduling: pending/CAS en admission blijven in
de bestaande JSON-state en OS-locks. De rapportdatabase beslist nooit of werk
wordt toegelaten of geselecteerd. Een DB-writefout bevestigt geen statefinish:
het receipt blijft staan en moet eerst worden verwerkt.

State-/receiptwrites gebruiken tempfile, file-fsync, atomische replace en
directory-fsync. `pending` bevat SHA, unieke request en markeertijd.
`last_result` bevat alleen de minimale operationele uitkomst, en `last_failure`
behoudt compacte metadata voor notificatiededuplicatie. Geen permanente
logvelden. Locks worden nooit verwijderd/vervangen: anders kunnen processen
verschillende inodes locken. Beschadigde/onbekende state faalt gesloten.

## Failure, rerun en ntfy

Een bevestigde failure wordt niet ieder uur opnieuw getest zolang dezelfde
request pending staat. Een nieuwe SHA wordt opnieuw werk; `rerun` maakt een
nieuwe request voor de huidige pending SHA (of het laatste resultaat wanneer
pending leeg is). Running/incomplete werk wordt wel opnieuw geprobeerd.

Alleen een nieuwe failed SHA ten opzichte van de bewaarde laatste failure mag
één ntfy-poging doen. Een expliciete rerun van dezelfde failing SHA verstuurt geen
herhaalde melding, ook niet na een tussentijds succes voor diezelfde SHA. Nieuwe
failure-SHAs mogen opnieuw melden. Idle, lock-busy en succes sturen niets.

Stel optioneel `WEEKENDKRANT_CI_NTFY_URL` in op de volledige HTTPS-topic-URL en
`WEEKENDKRANT_CI_NTFY_TOKEN` op een bearer token indien vereist. Er is geen nieuwe
Pythondependency: de POST gebruikt urllib, met 10 seconden timeout. De melding
noemt Weekendkrant CI, de korte SHA en `/home/weekendkrant/ci/failure` met repo en log.
Configuratie/secrets staan alleen in `ci/env`, nooit in Git. Notificatiefouten
geven een korte stderr-diagnose en veranderen het reeds opgeslagen CI-resultaat
niet. Er is geen aflevergarantie: een crash tussen resultaatcommit en POST kan
een melding missen; diagnostiek blijft de autoritatieve informatiebron.

## Lock en crashherstel

Een tweede cronstart probeert `runner.lock` met `LOCK_NB` en stopt stil als die
bezet is. De OS-lock vervalt zodra alle houdende filedescriptors sluiten.
Git-/testkindprocessen erven de runnerlock bewust: na een gedode parent kan de
volgende cron geen tweede suite starten of een nog gebruikte clone verwijderen.
Dit is lokaal met een echt gedood runnerproces en nog levend testproces getest.
Een vastgelopen, nog levend proces is geen stale lock; onderzoek/beëindig het
proces en verwijder nooit het lockbestand.

Afronding gebeurt onder de runnerlock in deze vaste volgorde:

1. Tests eindigen met hun echte exitcode; logfile wordt gefsynct. De uitkomst en
   eigen run-directory worden in een kleine atomische `completion.json` vastgelegd.
2. Bij groen wordt de eigen run-directory geheel verwijderd. Bij rood worden
   eerst oude DB-artifactverwijzingen NULL gemaakt, daarna wordt het oude
   artifact naar `failure.previous` hernoemd en de gereedstaande nieuwe directory
   naar `failure`. Beide renamegrenzen worden gefsynct. De oude checkout wordt
   nog niet vernietigd voordat het nieuwe artifact gepubliceerd is.
3. De DB-resultaatrow wordt idempotent geregistreerd. Alleen een bestaand nieuw
   artifact met bijpassende `result.json` en `test.log` krijgt een verwijzing.
4. Compacte operationele eindstatus en request-CAS-clear worden samen in JSON
   gecommit. Alleen succes voor dezelfde pending request mag pending wissen.
5. Het oude vervangingsartifact en completionreceipt worden verwijderd; daarna
   volgt eventueel één best-effort ntfy-poging.

Een crash vóór het receipt laat incomplete werkstate achter: de volgende vrije
runner ruimt de orphan op en test opnieuw. Een crash ná het receipt laat de
volgende runner eerst die ene afronding idempotent hervatten, vóór cleanup of
nieuw werk. Dat geldt ook na DB-commit maar vóór statefinish; er verschijnt geen
dubbele row en een nieuwere pending request wordt niet gewist.

| Crashmoment | Betekenis en herstel |
| --- | --- |
| Vóór/tijdens clone of tests | Geen bevestigde uitkomst; log staat tijdelijk in `work/run-*/test.log`. Na kindexit opnieuw testen. |
| Na exitcode 0, vóór duurzaam receipt | Geen groen rapport veronderstellen; opnieuw testen. |
| Na receipt, vóór DB-commit | Receipt voltooit cleanup/publicatie en registratie zonder een nieuwe test te verzinnen. |
| Tussen de twee failure-renames | Oud artifact staat nog in `failure.previous`; geen DB-row wijst naar het tijdelijk ontbrekende `failure`. Recovery publiceert de gereedstaande nieuwe run. |
| Na artifactpublicatie, vóór DB-commit | Manifest/log blijven beschikbaar; recovery registreert exact die failure. |
| Na DB-commit, vóór CAS | Row bestaat al; identieke registratie en statefinish zijn herhaalbaar. |
| Nieuwere pending tijdens afronding | CAS vergelijkt de eigen request; nieuwere request blijft staan. |
| Tweede cron tijdens actieve run | Stille niet-blokkerende exit, geen clone of tests. |

Een crash na het loskoppelen van oude DB-links kan een oude historische row
zonder artifactverwijzing achterlaten; dat is conservatief en beter dan een
verwijzing naar de verkeerde checkout. Normaal wordt elk completionreceipt
volledig gereconcilieerd voordat `cleanup`, `clear-failure` of nieuw werk doorgaat.
Bij beschadigd receipt/manifest stopt de runner zichtbaar en blijft het materiaal
voor operatoronderzoek staan. Dit is één kleine afrondingsreceipt, geen algemeen
transactiesysteem over filesystem en SQLite.

Na een harde kill/stroomuitval kan een onvoltooide tijdelijke directory
achterblijven. De volgende vrije runner reconcilieert eerst en ruimt vervolgens
alleen de eigen orphanprefix op, ook zonder pending werk. `cleanup` doet dit
handmatig onder dezelfde runnerlock. Een bewaard failureartifact valt nooit onder
deze gewone cleanup. At-least-once testen gaat vóór vals succes.

## Invoering na merge (nog niet geactiveerd)

Voer onderstaande stappen uit als `weekendkrant` op bibib, na gewone update en
fast-trackvalidatie van de gemergede code. Geen sudo of Node vereist. De runner
krijgt een stabiele externe venv en geïnstalleerde codekopie buiten de live app;
het zijn geen permanente Git-checkouts.

```bash
install -d -m 700 /home/weekendkrant/ci /home/weekendkrant/ci/bin
python3 -m venv /home/weekendkrant/ci/venv
/home/weekendkrant/ci/venv/bin/python -m pip install -r /home/weekendkrant/app/requirements.txt
install -m 600 /home/weekendkrant/app/ci_runner.py /home/weekendkrant/ci/bin/ci_runner.py.new
mv /home/weekendkrant/ci/bin/ci_runner.py.new /home/weekendkrant/ci/bin/ci_runner.py
install -m 700 /home/weekendkrant/app/start_ci.sh /home/weekendkrant/ci/bin/start_ci.sh.new
mv /home/weekendkrant/ci/bin/start_ci.sh.new /home/weekendkrant/ci/bin/start_ci.sh
if [[ ! -e /home/weekendkrant/ci/env ]]; then
    install -m 600 /dev/null /home/weekendkrant/ci/env
fi
```

Bovenstaande guard maakt `env` uitsluitend bij eerste installatie aan. Een
bestaand bestand en zijn private inhoud blijven behouden. Bewerk de configuratie
met bijvoorbeeld `nano /home/weekendkrant/ci/env`:

```bash
WEEKENDKRANT_CI_STATE=/home/weekendkrant/ci
WEEKENDKRANT_CI_PYTHON=/home/weekendkrant/ci/venv/bin/python
WEEKENDKRANT_CI_SOURCE=https://github.com/willemg/weekendkrant.git
TIKTOKEN_CACHE_DIR=/home/weekendkrant/.cache/tiktoken
# Optioneel, vul de eigen bestaande ntfy-topic-URL en eventueel token in:
# WEEKENDKRANT_CI_NTFY_URL=https://ntfy.sh/EIGEN_TOPIC
# WEEKENDKRANT_CI_NTFY_TOKEN=EIGEN_TOKEN
```

De bestaande tiktokencache mag worden gedeeld. De externe venv bevat de vastgelegde
requirements (nu `tiktoken==0.12.0`) en wordt niet per clone opnieuw opgebouwd.
Wijzig hem niet tijdens een run. Dependency-upgrades vereisen bewust venvonderhoud
vóór activering van de betrokken SHA; ontbrekende dependencies geven een failure.
Dit is geen hermetische per-SHA dependencyresolver. Een parallelle nieuwe venv
met een ander `WEEKENDKRANT_CI_PYTHON`-pad is een eenvoudige upgradeoptie.
Voer de eerste run met beschikbare tokenizerdata/netwerk uit; de bestaande cache
blijft buiten de wegwerpclone. De repo zelf wordt nooit uit de live app gekopieerd.

Activeer de trigger voor de normale deploymentshell, bijvoorbeeld via een export
in de shellconfiguratie van `weekendkrant`:

```bash
export WEEKENDKRANT_CI_STATE=/home/weekendkrant/ci
cd /home/weekendkrant/app
git pull --ff-only
./start_tests.sh
```

Dit is het gewone, door de operator uitgevoerde deploymentpad, geen CI-worker.
Bij een schone, groene fast-track staat nu de exacte SHA pending. De trigger is
bewust opt-in; alleen cron installeren zonder deze export levert geen nieuw werk.

Voeg daarna met `crontab -e` deze regel toe aan de crontab van `weekendkrant`:

```cron
0 * * * * /home/weekendkrant/ci/bin/start_ci.sh
```

De wrapper laadt `ci/env`, wisselt naar de externe statedirectory en start één
runner. Geen stdout bij idle/succes/bekende failure; stderr blijft voor
operationele fouten beschikbaar aan cron. Zonder cronmail kan dezelfde wrapper
handmatig worden uitgevoerd; failurediagnostiek staat uitsluitend in het artifact.
De uurlijkse start is geen belofte over eindtijd of beschikbaarheid.

Bij een gewone runnerupdate herhaal je uitsluitend de vier install/mv-opdrachten
voor `ci_runner.py` en `start_ci.sh`, buiten een actieve run. Behoud `ci/env`,
state, rapportdatabase en failureartifact; maak geen nieuwe lege configuratie.
Venvonderhoud is alleen bij gewijzigde dependencies nodig. Er is geen automatische self-update of productiecron-
installatie. Voor rollback: verwijder de cronregel en unset de triggerexport;
bewaar state en failurediagnostiek voor onderzoek.

## Operatoropdrachten

De geïnstalleerde runner kan met de externe venv of systeem-Python worden
geïnspecteerd; hijzelf gebruikt alleen de standaardbibliotheek.

```bash
# Status inclusief pending, laatste resultaat/failure en actuele lockbezetting
python3 /home/weekendkrant/ci/bin/ci_runner.py status

# Alleen de exacte pending request
python3 /home/weekendkrant/ci/bin/ci_runner.py status --pending

# Laatste resultaat (en overige state) direct bekijken
python3 -m json.tool /home/weekendkrant/ci/state.json

# Laatste compacte operationele failuremetadata
python3 /home/weekendkrant/ci/bin/ci_runner.py status --failure

# Compacte historie (laatste 20 resultaten)
python3 /home/weekendkrant/ci/bin/ci_runner.py report

# Hetzelfde rechtstreeks via SQLite, indien sqlite3 CLI geïnstalleerd is
sqlite3 /home/weekendkrant/ci/report.sqlite3 \
  'SELECT sha,status,finished_at,duration_seconds,artifact_path FROM ci_runs ORDER BY id DESC LIMIT 20;'

# Exacte failing checkout en volledige failurelog onderzoeken
cd /home/weekendkrant/ci/failure/repo
git rev-parse HEAD
git status
git show --stat
less /home/weekendkrant/ci/failure/test.log

# Na onderzoek alleen het zware artifact opruimen, historie behouden
python3 /home/weekendkrant/ci/bin/ci_runner.py clear-failure

# Handmatig hetzelfde pad als cron uitvoeren
/home/weekendkrant/ci/bin/start_ci.sh

# Rerun aanvragen en direct uitvoeren
python3 /home/weekendkrant/ci/bin/ci_runner.py rerun
/home/weekendkrant/ci/bin/start_ci.sh

# Bewust een specifieke volledige SHA kiezen, ook voor een rollback
# Vervang de voorbeeld-SHA door de daadwerkelijk gewenste 40 hextekens.
python3 /home/weekendkrant/ci/bin/ci_runner.py mark --sha 0123456789abcdef0123456789abcdef01234567 --force

# Lock/runstatus en bijbehorende processen onderzoeken
python3 /home/weekendkrant/ci/bin/ci_runner.py status
ps -u weekendkrant -o pid,ppid,etime,args
lslocks

# Na een crash eigen tijdelijke clones veilig opruimen (no-op bij bezette lock)
python3 /home/weekendkrant/ci/bin/ci_runner.py cleanup
```

Een `running`-resultaat met `runner_busy: false` is incomplete uitvoering, geen
succes. Een `failed`-resultaat blijft rood zichtbaar ondanks een stille volgende
cronstart. Controleer bij failure eerst de DB-row en `failure/test.log`, dan
bronbereikbaarheid, Pythonomgeving en de concrete testfout. `status --failure`
is compacte operationele metadata; `report` is de historische rapportage. Kies na herstel
bewust `rerun`; een nieuwe deployment-SHA mag de oude pending vervangen.
Een historische row met `artifact_path = NULL` kan zowel groen als een oudere
rode run zonder nog bewaarde checkout beschrijven; de statuskolom blijft leidend.
Bij een incomplete run kun je vóór cleanup `work/run-*/test.log` bekijken.
Een achtergebleven `completion.json` wordt automatisch door `run` of `cleanup`
herwerkt; verwijder het niet handmatig zonder onderzoek.

## Testbewijs en grenzen

`tests/fast_track.txt` selecteert voor fase 10 alleen `test_ci_runner` en
`test_test_runner`. Nieuwe tests dekken state/coalescing/CAS, same-SHA-reruns,
locking, compacte SQLite-historie/idempotentie, artifactvervanging, successcleanup,
behoud/clear van een oudere failure, outputnoodrem, ntfy met fakes, crashherstel,
het niet-destructieve env-commando, cleanup,
Git-omgevingisolatie en de echte fast-tracktrigger. Kleine lokale Git-fixtures
bewijzen exact-SHA, verse clones, onaangeraakte broncheckout en een gedode parent.
Fixtures gebruiken een mini-entrypoint, nooit een netwerkclone of de volledige
projectsuite. Bestaande runnerfixtures gebruiken ook `--all` tegen hun kleine
geïsoleerde testmodules; dat is geen volledige Weekendkrant-run.

Tijdens deze implementatie is uitsluitend `./start_tests.sh` als validatiecommando
gebruikt. Geen echte `./start_tests.sh --all`, productiecron, ntfy-bericht of
remote deployment uitgevoerd. De eerste echte volledige-suite-CI en controle van
productieresultaat/notificatie blijven een afzonderlijke gate na merge/activering.

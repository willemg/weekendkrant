# Lokale volledige CI (fase 10)

De volledige Python-suite is te traag voor iedere ontwikkeliteratie of pull.
`./start_tests.sh` blijft de synchrone fast-trackgate uit de geversioneerde lijst.
Een optionele lokale trigger registreert na een geslaagde, schone fast-track de
exacte HEAD voor een afzonderlijke volledige CI-run. Groen in de fast-track is
geen bewijs dat de volledige suite groen is.

De CI is een lokaal cronproces, zonder daemon, dispatcher, SQLite of externe
CI-provider. De implementatie en gerichte tests zijn beschikbaar; productiecron,
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

## Persistente state, writes en resultaten

Alles staat standaard onder `/home/weekendkrant/ci`, eigendom van `weekendkrant`,
met private directoryrechten. Er is één atomisch JSON-statebestand, zodat een
resultaat en pending-clear geen afzonderlijke crashgevoelige commits vormen.

| Bestand/map | Eigenaar en functie |
| --- | --- |
| `state.json` | Trigger/operator schrijft `pending`; runner schrijft `last_result` en `last_failure`. Schema `version: 1`. |
| `state.lock` | Korte exclusieve `flock` voor iedere read-modify-write en state-tempcleanup. |
| `runner.lock` | Niet-blokkerende exclusieve `flock` voor volledige run en orphan-workcleanup. |
| `current.log` | Runner bewaart maximaal de laatste 128 KiB gecombineerde stdout/stderr plus command-/foutdiagnose, ook tijdens uitvoering. |
| `work/run-*/repo` | Alleen tijdelijke verse clone; normaal na iedere uitkomst verwijderd. |
| `.state-*` | Alleen tijdelijke atomaire writes; na crash onder statelock opgeruimd. |
| `bin/`, `venv/`, `env` | Geïnstalleerde runner, externe Pythonomgeving en private operatorconfiguratie, geen Git-working tree. |

Een statewrite schrijft een nieuwe tijdelijke file, flusht en fsynct die,
vervangt atomisch `state.json` en fsynct de directory. Locks worden nooit
verwijderd/vervangen: anders zouden processen verschillende inodes kunnen locken.
Een beschadigde/onbekende state faalt gesloten; hij wordt niet als idle of groen
geïnterpreteerd. Herstel vereist operatoronderzoek.

`pending` bevat `sha`, een unieke `request` en `marked_at`. De requestidentiteit
maakt ook een geforceerde rerun van dezelfde SHA tijdens een lopende run veilig.
`last_result` bevat die identiteit, `status`, `started_at`, `finished_at`,
`exitcode` en het gekozen Pythonpad. Tijden zijn UTC met offset.

De runner legt eerst `running` vast, test buiten de statelock en schrijft daarna:

- `succeeded`, exitcode 0: pending wordt uitsluitend gewist als de volledige
  pending request nog gelijk is aan de eigen snapshot;
- `failed`, niet-nul exitcode: pending blijft staan, en `last_failure` krijgt
  resultaatmetadata plus de laatste 128 KiB diagnostiek in veld `log`.
  Clone-, checkout- en testcommandofouten falen allemaal; een infrastructuur-
  exception krijgt exitcode 2. Een signaalexit blijft negatief in JSON en wordt
  voor de CLI naar de gebruikelijke `128 + signaalnummer` vertaald.

Komt D binnen terwijl C getest wordt, dan blijft D pending wanneer C eindigt.
Een succes voor C blijft geldig bewijs over C, maar zegt niets over D. Een
geforceerde nieuwe request voor C blijft eveneens pending. Er zijn geen stille
lost updates of vals groene onbehandelde SHAs.

Er is geen groeiende historie: één laatste resultaat, één laatste failure met
begrensde log en één begrensde current-log. Latere successen wissen de laatste
failure niet. Daarmee blijft de vorige fout onderzoekbaar, zonder oude clones
te bewaren. Een nieuwere failure vervangt de vorige failurediagnostiek.
`current.log` is best-effort crashdiagnostiek, geen atomisch resultaatbewijs;
alleen het gefsyncte `state.json` bevestigt de eindstatus.

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
noemt Weekendkrant CI, de korte SHA en de lokale `state.json`-diagnostiek.
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

| Crashmoment | Bewaarde betekenis en volgende activatie |
| --- | --- |
| Vóór clone | Pending of `running`, geen succes; volgende start probeert opnieuw. |
| Tijdens clone | `running`; kind kan lock behouden tot exit, daarna orphan weg en verse clone. |
| Tijdens tests | Zelfde; `current.log` biedt begrensde uitvoer, geen bevestigde eindstatus. |
| Na testsucces, vóór resultaatcommit/CAS | Nog `running` en pending: opnieuw testen, nooit succes veronderstellen. |
| Tijdens atomische resultaatwrite | Oude volledige state of nieuwe volledige state; geen half resultaat met een losse pending-clear. |
| Nieuwere pending tijdens run | CAS vergelijkt de eigen request; nieuwere pending blijft onaangeraakt. |
| Tweede cron tijdens actieve run | Stille niet-blokkerende exit, geen clone of tests. |

Normale successen, failures en afgevangen exceptions ruimen de clone op via
`TemporaryDirectory`. Een harde kill/stroomuitval kan rommel achterlaten; de
volgende vrije runner ruimt de eigen prefix op vóór nieuw werk, ook wanneer er
geen pending werk is. `cleanup` doet dit handmatig onder dezelfde runnerlock.
At-least-once testen gaat vóór de besparing van een herhaalde suite.

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
install -m 600 /dev/null /home/weekendkrant/ci/env
```

Maak `env` alleen bij eerste installatie leeg, niet bij updates. Bewerk daarna
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
handmatig worden uitgevoerd; testdiagnostiek staat begrensd in de state/log.
De uurlijkse start is geen belofte over eindtijd of beschikbaarheid.

Werk runnerkopie en wrapper bij toekomstige relevante deployments opnieuw bij,
buiten een actieve run. Er is geen automatische self-update of productiecron-
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

# Laatste failure met SHA, tijden, exitcode en log
python3 /home/weekendkrant/ci/bin/ci_runner.py status --failure

# Laatste begrensde uitvoer, ook nuttig na een crash
cat /home/weekendkrant/ci/current.log

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
cronstart. Controleer bij failure eerst SHA/status/exitcode en `last_failure["log"]`,
dan bronbereikbaarheid, Pythonomgeving en de concrete testfout. Kies na herstel
bewust `rerun`; een nieuwe deployment-SHA mag de oude pending vervangen.
De log in JSON is het veld `log` binnen `last_failure`, geen los logbestand.

## Testbewijs en grenzen

`tests/fast_track.txt` selecteert voor fase 10 alleen `test_ci_runner` en
`test_test_runner`. Nieuwe tests dekken state/coalescing/CAS, same-SHA-reruns,
locking, bounded failurediagnostiek, ntfy met fakes, crashherstel, cleanup,
Git-omgevingisolatie en de echte fast-tracktrigger. Kleine lokale Git-fixtures
bewijzen exact-SHA, verse clones, onaangeraakte broncheckout en een gedode parent.
Fixtures gebruiken een mini-entrypoint, nooit een netwerkclone of de volledige
projectsuite. Bestaande runnerfixtures gebruiken ook `--all` tegen hun kleine
geïsoleerde testmodules; dat is geen volledige Weekendkrant-run.

Tijdens deze implementatie is uitsluitend `./start_tests.sh` als validatiecommando
gebruikt. Geen echte `./start_tests.sh --all`, productiecron, ntfy-bericht of
remote deployment uitgevoerd. De eerste echte volledige-suite-CI en controle van
productieresultaat/notificatie blijven een afzonderlijke gate na merge/activering.

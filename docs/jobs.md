# Generieke jobs, attempts en control-plane (schema 10)

Fase 7: de startketen gebruikt nu de [algemene dispatcher](dispatcher.md), met ready-first
selectie, persistente pause en globale/rolconcurrency. `start_weekendkrant_executor`
blijft het enige startpunt; `/executor/start` is canoniek en de oude
`/executor/sherlock/start`-route blijft alias. Schema 10 bewaart generieke immutable
activationreceipts en behoudt alle schema-9-audit. Alleen Sherlock is geregistreerd;
geen Leonardo-jobs of verwerking van offers. Deze bronwijziging is geen deployment.
De onderstaande fase-5-beschrijving blijft van toepassing op Sherlock-opdrachten.

Dit omvat de lokale opslaglaag van fase 3 en de generieke MCP/control-plane
van fase 4. Fase 5 voegt de [Sherlock-executoradapter](sherlock-executor.md) toe:
atomaire productie/start en gefencete bron-/fichewrites. Fase 7 voegt de algemene
dispatcher toe; andere productierollen zijn nog niet geïmplementeerd. Operationele
invoering van de dispatcher volgt afzonderlijk.
Ariadnes consumentencontract blijft behouden. `attempts` blijft Ariadnes foutaudit;
`job_attempts` is uitsluitend de nieuwe generieke uitvoeringsaudit.

## Identiteit, grenzen en transacties

`JobStore(connection)` gebruikt de centrale migraties en een caller-owned,
inactieve SQLite-connection. Mutaties gebruiken `BEGIN IMMEDIATE`, lezen de
backendklok na het verkrijgen van de schrijflock en committen alle betrokken
records samen. Bij fouten volgt rollback. Modelwerk, netwerkverkeer en
bestandspublicaties gebeuren nooit in die transactie. Een actieve callertransactie
wordt geweigerd, niet stilzwijgend gecommit. Connection-timeout/lockfouten blijven
zichtbaar; opnieuw proberen vereist dezelfde operatie-identiteit.

Een job heeft een stabiele oplopende `id`, immutable rol, inputreferenties,
outputcontractreferentie, vaste leaseduur en creatietijd. Status, update- en
eindtijd en geaccepteerde outputreferenties beschrijven de lifecycle. Input en
output bevatten maximaal 32 concrete artifact-/versiereferenties van maximaal
512 tekens. De outputcontractreferentie is verplicht, maximaal 512 tekens; de rol
is niet-lege tekst van maximaal 128 tekens. Het opslagschema interpreteert geen
rol of artifacttype. De producent moet bestaande, concrete immutable versies
refereren en het contract moet inhoud, context, output en toegestane acties
begrenzen. Deze laag controleert vorm en execution identity, geen artifactinhoud
of redactionele contracten die pas in latere fasen bestaan.

Iedere claim maakt een afzonderlijke attempt met oplopende `id`, unieke
backendgegenereerde willekeurige token, globale `activation_id`, jobreferentie,
starttijd, `lease_until`, status, eindtijd, outputreferenties en eventuele fout
(maximaal 2048 tekens). De oplopende attempt-ID vormt de fencing-generatie, de
token bewijst bezit van de claim. De unieke activation-ID voorkomt een tweede
job/attempt binnen dezelfde scheduled activatie, ook voor een andere rol of job.
De control-plane vereist die identiteit bij claim. De vertrouwde activationadapter
moet haar globaal uniek en stabiel aanleveren, ook bij retry. Tokens worden niet
gelogd of aan andere executors blootgesteld. De eerste caller-supplied occurrencebinding staat in [de executorinstructie](agents/executor.md); een native platformattest bestaat niet.

Alle tijden zijn UTC ISO 8601 met microseconden. Leaseduur is expliciet 1..86400
gehele seconden, standaard 3600 seconden. Een lease geldt uitsluitend zolang
`now < lease_until`; op de grens vervalt hij. Geen heartbeat of leaseverlenging:
een job moet binnen zijn vooraf gekozen duur afronden. De backendklok moet
betrouwbaar en gesynchroniseerd zijn; workerklokken beslissen niet. Dit is een
autorisatiegrens, geen proceskill of bewijs dat model-/netwerkwerk gestopt is.

De default van 3600 seconden is in de eerste meetfase een voorlopige
conservatieve veiligheidsgrens, geen gemeten optimum of gewenste jobduur.
Lange maar gezonde jobs mogen binnen die grens worden geobserveerd. Een job die
richting één uur loopt levert nuttige operationele meetinformatie voor later
lease- en capaciteitsbeleid; dat is geen doel om elke job een uur te laten duren.
De lease blijft per job configureerbaar, met dezelfde bovengrens van 86400 seconden.

## Lifecycle en herstel

| Operatie/conditie | Job | Attempt | Gevolg |
| --- | --- | --- | --- |
| `create(role, input_refs, output_contract_ref, lease_seconds=3600)` | `ready` | Geen | Retourneert stabiele job-ID; iedere create is een nieuwe opdracht |
| `claim(job_id, activation_id)` op ready | `running` | Nieuwe `running` | Retourneert job-ID, attempt-ID, token en lease-einde |
| Zelfde claim opnieuw, binnen lease | `running` | Dezelfde | Exact hetzelfde claimantwoord, geen nieuwe attempt |
| Andere claim op niet-ready | Ongewijzigd | Geen nieuwe | `None`; geen selectie of dispatcher |
| `finish(claim, 'succeeded', output_refs)` | `succeeded` | `succeeded` | Referenties en terminale tijden atomisch bevestigd |
| `finish(claim, 'failed', output_refs, error)` | `failed` | `failed` | Bekende terminale fout; geen automatische retry |
| `finish(claim, 'uncertain', output_refs, error)` | `blocked` | `uncertain` | Onzekere effecten eerst onderzoeken |
| Lease verlopen | `blocked` | `expired` | Oude claim kan geen resultaat meer laten accepteren |
| `reconcile(..., 'retry', evidence_ref)` | `ready` | Blijft immutable gesloten | Alleen na bewezen stop en veilige heruitvoering; volgende activatie krijgt nieuwe attempt/token |
| `reconcile(..., 'succeeded'/'failed', evidence_ref, output_refs)` | Terminal | Blijft immutable gesloten | Bekende effecten/resultaten expliciet bevestigd met aparte herstelaudit |

`recover_expired()` zet alle verlopen attempts atomisch in quarantaine en is
herhaalbaar. Ook claim/finish controleren expiry onder de schrijflock; een
aparte sweeper is geen veiligheidsvoorwaarde. Een finish op een verlopen claim
commit de quarantaine en geeft vervolgens `ValueError`. Onbekende, vervalste,
superseded of conflicterende claims worden geweigerd. Een exact herhaalde
bevestigde finish (status, outputs en fout identiek) is een no-op, ook na het
lease-einde. Het bewijs is de opgeslagen finish, niet de herinnering van de worker.
Een onbevestigde finish moet eerst dezelfde operatie herhalen of opgeslagen state
raadplegen, niet alvast opnieuw publiceren. `get(job_id)` en `attempts(job_id)`
geven inspecteerbare state; ze maken een verlopen lease niet opnieuw geldig.

Reconciliatie is een **trusted recovery-operatie**. Fase 4 biedt hiervoor een
afzonderlijk geauthenticeerd operatorendpoint, geen gewone MCP-tool.
Een niet-lege bewijsreferentie moet naar een controle verwijzen die aantoont dat
de oude executor gestopt is en de effecten bekend zijn. Voor `retry` moet ook
vaststaan dat heruitvoering veilig is: geen onbehandelde effecten, of geverifieerde
idempotentie bij de ontvanger. De opslaglaag controleert de referentie en dat de
attempt de laatste geblokkeerde poging van deze job is; zij kan het inhoudelijke
bewijs niet zelf beoordelen. Bij onbekende effecten blijft de job blocked.
Alleen tijdsverloop of een nieuwe schedulerstart is onvoldoende bewijs.

Iedere reconciliatie krijgt één immutable `job_recoveries`-record, gekoppeld aan
de oude attempt, met beslissing, bewijs, outputs en tijd. Een oude attempt wordt
niet achteraf van expired/uncertain naar succeeded herschreven. Een herhaalde lokale `JobStore.reconcile` wordt geweigerd; de fase-4-control-plane
herhaalt met dezelfde bevestigde operation-ID uitsluitend het opgeslagen antwoord.
Inspecteer de opgeslagen beslissing voordat je een nieuwe actie neemt. Outputregistratie publiceert geen artifact en veroorzaakt
geen externe side effect. Dat voorkomt een verborgen exactly-once-belofte.

## Crash- en concurrency-invarianten

- Twee connections kunnen dezelfde ready job niet tegelijk claimen. Statuswijziging
  en attemptinsert zitten onder dezelfde SQLite-schrijfslot; een unieke partial
  index bewaakt bovendien maximaal één running attempt per job.
- Crash vóór commit laat geen halve claim, finish of herstelaudit achter.
  Crash na commit behoudt die state; een verloren antwoord verandert de uitvoering
  niet in een nieuwe job of nieuwe attempt.
- Expiry geeft nooit automatisch toestemming tot overlappende heruitvoering.
  Ook als de oude executor blijft werken, wordt zijn late resultaat afgewezen.
  Alleen reconciliatie met bewezen stop kan een volgende attempt toestaan.
- Lease/fencing beschermen deze opslaglaag. Externe effecten zijn niet door SQLite
  te fencen. Latere publicatieadapters moeten vóór effects claimvalidatie, eigen
  idempotentie en zo nodig ontvangerfencing implementeren. De bestaande `/ingress`
  is daarvoor nog niet aangepast en wordt niet door deze jobs aangeroepen.
- Jobidentiteit, gesloten attempts en herstelaudit mogen niet overschreven worden.
  Delete en `INSERT OR REPLACE` van bestaande auditidentiteiten worden geweigerd.
  Terminale jobs zijn immutable. Rechtstreeks SQL is geen ondersteunde lifecycle-API.

Een backendherstart start geen nieuwe uitvoering. Voor verdere voortgang roept
lokale recovery `recover_expired()` aan en onderzoekt blocked jobs. Automatisch
retryen zonder bewijs is bewust uitgesloten. Crashsafe veiligheid gaat hier boven
automatische voortgang; een dispatcher en recoverybeleid zijn latere integratie.

## Migratie en validatie

Migratie `007_jobs.sql` voegt uitsluitend `jobs`, `job_attempts`, `job_recoveries`
en hun indices/constraints/triggers toe. Geen bestaande tabel, rij, provenance,
Sherlock-run of Ariadne-attempt verandert; er is geen backfill. Lege databases en
upgrades volgen dezelfde keten. DDL en `user_version=7` committen samen, herhalen
is een no-op, een mislukte stap blijft op versie 6. De bestaande runtime kan na
upgrade verder werken zonder generieke jobs te maken.

De jobtests controleren onafhankelijke SQLite-connections, gelijktijdige claimers,
één activatie tegenover twee jobs, finish versus expiry, echte abrupte procesexits
vóór/na commit, herstart, late/forged tokens, exacte finishretry, onzekere effecten,
reconciliatie, rollback, schema-upgrade en auditimmutability. De bestaande
systeemtest blijft het HTTP-ingress → SQLite → Ariadne → part/revision-pad testen;
hij beweert geen generieke control plane te testen.

```bash
python -m unittest discover -s tests -p 'test_jobs.py' -v
python -m unittest discover -s tests
python -m unittest discover -s tests -p 'test_system_e2e.py' -v
```

Validatie van deze fase op 14 oktober 2026: 214 tests groen in de volledige
Python-suite, waaronder 22 jobtests; de afzonderlijke systeemtest is 2/2 groen.
Deze lokale uitvoering gebruikt Python 3.12; het operatorbewijs van 192 tests
op bibib betreft de voorafgaande fase-2.5-runtime.


## Fase 4: protocol, identiteit en operation receipts

`job_control.JobControl` bouwt op de bestaande lifecycle. Het claimt uitsluitend
het expliciete `job_id`: jobs worden lokaal voorbereid met `JobStore.create`.
Deze expliciete control-plane selecteert zelf geen werk en heeft geen MCP-create.
De fase-7-dispatcher selecteert apart en deelt de claim-/receiptinvarianten.
De claim/start is één atomaire operatie, geen aparte tweede startcall.
Het antwoord bevat `job_id`, `attempt_id` (fencing-generatie), geheime `token`,
`lease_until`, `role`, `input_refs` en `output_contract_ref`. Een onbeschikbare job
geeft `{"claim": null}`. Resultaten registreren concrete bestaande versies;
geen van deze operaties voert modelwerk uit of publiceert artifacts.

| MCP-tool / HTTP POST | Vereiste argumenten | Semantiek en retry |
| --- | --- | --- |
| `claim_weekendkrant_job` / `/jobs/claim` | `operation_id`, `job_id`, `activation_id` | Specifieke ready job claimen. Exacte bevestigde retry geeft dezelfde attempt/token en oorspronkelijke lease terug, ook als de attempt ondertussen gesloten is. Een bevestigd null-antwoord blijft null. |
| `finish_weekendkrant_job` / `/jobs/finish` | `operation_id`, `job_id`, `attempt_id`, `token`, `status`, `output_refs`; optioneel `error` | `succeeded` of `failed` is terminaal; `uncertain` blokkeert. Bevestigde exacte operatie herhaalt alleen het antwoord. Nieuwe operatie-ID met exact dezelfde al bevestigde finish volgt de bestaande no-op-semantiek; conflicterende finish wordt geweigerd. |
| `abandon_weekendkrant_job` / `/jobs/abandon` | `operation_id`, `job_id`, `attempt_id`, `token`, `error` | Conservatieve finish als uncertain met lege outputs, job blocked. Geen automatische heruitvoering. Exacte bevestigde retry herhaalt alleen het antwoord. |
| `validate_weekendkrant_claim` / `/jobs/validate` | `job_id`, `attempt_id`, `token` | Actuele claimstatus, `valid` en lease; geen gecachte receipt of operation-ID. Herhalen kan na tijdsverloop een andere status geven. Verlopen attempts worden persistent geblokkeerd. Onbekende/vervalste claim geeft conflict. |
| Alleen operator: `/jobs/reconcile` | `operation_id`, `job_id`, `attempt_id`, `decision`, `evidence_ref`; optioneel `output_refs` | Beslissing `retry`, `succeeded` of `failed`, met hetzelfde bewijscontract als lokale recovery. Exacte bevestigde retry geeft de oorspronkelijke bevestiging terug, ook na een nieuwe attempt; voert geen tweede recovery uit. |

**Een receipt bewijst een oude commit, geen actuele uitvoeringsbevoegdheid.**
Controleer een claim met validate vóór uitvoering en controleer het lease-einde.
Een stale claimreceipt mag geen inhoudelijk werk opnieuw starten. Finish valideert
opnieuw onder de schrijfslot; een race na validate kan dus alsnog finish weigeren.
Externe effecten vereisen een eigen adapter met idempotentie en ontvangerfencing,
plus onderzoek bij onzeker antwoord. Validate alleen voorkomt geen side-effectrace.

De expliciete operator-caller kiest één globale `activation_id` per activation en behoudt
haar gedurende de hele activation, over tools, rollen en transportretries heen.
Een nieuwe toolcall of een gesloten attempt is geen nieuwe activation. De database
weigert een tweede attempt bij dezelfde activation, ook voor een andere job.
Caller-selected IDs zijn uitsluitend operator-protocolidentiteiten, geen bewijs
van een echte schedulerstart. De scheduled route gebruikt backend-owned identiteit.

Iedere expliciete operator-mutatie vereist een globaal unieke, niet-lege `operation_id` van maximaal
128 tekens. Gebruik een UUID of namespaced unieke identiteit. Behoud ID én exacte
argumenten bij timeout, verloren antwoord, HTTP 503 of onzekere bridge-response.
JSON-objectkeyvolgorde is irrelevant; expliciete optional null versus weglaten en
volgorde van outputreferenties horen bij de identiteit. Hergebruik van een ID met
een ander operatietype of andere argumenten geeft HTTP 409, nooit nieuwe uitvoering.
Een onbevestigde fout schrijft geen receipt; dezelfde operatie mag opnieuw worden
aangeboden zodra de transport-/lockfout weg is. Een 400 vereist inputcorrectie,
een 401 authenticatiecorrectie en een 409 stateonderzoek. De bridge retryt niet
zelf en maakt nooit nieuwe IDs. Transportretry is geen retry van jobuitvoering.

Migratie `008_job_operations.sql` voegt immutable `job_operations` toe met
operation-ID, operatietype, SHA-256 van canonieke argumenten, job-/attempt-ID,
compact antwoord zonder token en backendtijd. Geen payload, reasoning of secret
wordt in requestlogs geschreven. Claimtokens blijven uitsluitend in de bestaande
attempttabel en worden bij claimreplay daaruit teruggelezen. Receipts hebben geen
retentietermijn en mogen niet worden verwijderd of overschreven.

Receipt en lifecyclemutatie committen samen in één korte `BEGIN IMMEDIATE`.
De bestaande lifecycleprimitieven gebruiken intern diezelfde transactie en klok;
een savepoint rolt een geweigerde operatie terug zonder de vooraf vastgestelde
expiryquarantaine te verliezen. De klok wordt pas na het verkrijgen van de lock
gelezen. Geen HTTP-verkeer, filewerk of modelcall vindt plaats onder de schrijfslot.
Vóór commit crashen laat geen attempt/receipt achter, erna blijft beide bestaan.
SQLite-lockfouten blijven HTTP 503; concurrency geeft geen dubbele attempts.

De gewone tools gebruiken de bestaande ingresssecret en MCP-userauthenticatie.
Recovery vereist uitsluitend `WEEKENDKRANT_RECOVERY_TOKEN`, een apart operatorsecret
in de backendomgeving dat van de ingresssecret moet verschillen. Zonder die variabele
is het endpoint gesloten. Bewaar het nooit in Sites/pluginenv of workercontracten.
De endpointauthenticatie begrenst wie bewijs mag bevestigen; de backend beoordeelt
het inhoudelijke bewijs zelf niet. Expirysweeping blijft lokaal beschikbaar met
`JobStore.recover_expired`; tijdsverloop maakt een blocked job nooit automatisch ready.

Alle JSON-objecten hebben strikte velden. IDs zijn positieve veilige JSON-integers
(maximaal 9007199254740991). Artifact-, token-, fout- en activationgrenzen volgen
het bovenstaande opslagcontract; plugin en backend controleren dezelfde grenzen.
Bestaande vijf Sherlock/fichetools en hun routes, schemas en runtime blijven bestaan.
De generieke toolnamen worden uitsluitend toegevoegd. Deze implementatie en lokale
tests bewijzen geen gepubliceerde Sites-deployment of productie-upgrade.

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m unittest discover -s tests -p 'test_system*.py' -v
# Afzonderlijk in de plugin-developmentomgeving:
npm --prefix plugin/weekendkrant_ingress test
npm --prefix plugin/weekendkrant_ingress run test:backend
```

## Testlagen en bewijsgrenzen

- Weekendkrant/bibib: Python unit-, integratie- en systeemtests van backend,
  SQLite en Ariadne. `./start_tests.sh` en `unittest discover -s tests` starten
  geen Node en vereisen geen Node-installatie. De HTTP-controltests en persistente
  operationtests blijven operation-ID replay, verloren antwoorden, idempotentie,
  lease/fencing, concurrency en crashherstel bewijzen.
- MCP/Sites-plugin: afzonderlijke JavaScript-tests en pluginbuild. De optionele
  `plugin/weekendkrant_ingress/tests/bridge_backend.py` is een expliciete plugin-
  developmenttest van de echte JavaScript-brug → HTTP → tijdelijke SQLite, met
  verloren claim- en finishantwoorden na commit. Alleen discovery/bestemming worden
  naar loopback gemapt. Hij staat buiten de Python-discovery en draait alleen via
  de expliciete pluginopdracht, nooit via `./start_tests.sh`.
- Het werkelijk gepubliceerde Sites → tunnel → backend-pad wordt bewezen door de
  bestaande afzonderlijke deployment-smoke, niet door een lokale bridge-test.

Plugin-development vereist Node.js >=18.3.0; de versie-/featurepreflight geldt
uitsluitend voor die laag. De optionele backendfixture gebruikt daarnaast Python,
zonder extra Python-packages. Zie [opdrachten en featureminimum](../plugin/weekendkrant_ingress/README.md#lokaal-testen-en-bouwen).
De bestaande offline tokenizercache-preflight blijft gelden voor de Python/Ariadne-
systeemgate op bibib.

Validatie na scheiding van de testlagen op 14 oktober 2026: **230 Python-tests**,
waaronder 13 control-protocoltests, 3 HTTP-tests en **2 systeemtests** inclusief
cachepreflight, groen met Node volledig buiten `PATH`. **32 JavaScript-plugintests**,
de afzonderlijke optionele bridge/backend-test en de pluginbuild groen. Dit is
lokaal bewijs, geen uitvoering op bibib of nieuwe deployment-smoke.


## Scheduled executorprotocol, fase 9.5

Bovenstaande caller-identiteiten horen bij de expliciete operator-control-plane.
De scheduled executor meldt zich zonder argumenten aan, krijgt executor_id en
haalt daarmee precies zijn reeds gebonden job op. Klok, activation_id en interne
operatie-identiteiten worden volledig op bibib bepaald. Zie [dispatcher](dispatcher.md).

De publieke finish/abandon-tools vereisen geen operation_id: de backend leidt
één terminale operatie af uit de gebonden job/attempt. De bestaande requestdigest,
receipt en atomaire mutatie blijven behouden. Een gewijzigde terminale payload of
andere terminale actie conflicteert. De expliciete operatorroute behoudt optioneel
haar bestaande identiteit; deze wordt niet van de scheduled executor gevraagd.

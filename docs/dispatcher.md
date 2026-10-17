# Algemene dispatcher (fase 7)

Zie de [runtimecontractgrens en begrippen](roles.md#runtimecontracten-fase-85):
`roles/*.md` zijn de canonieke versioned runtime-artifacts voor nieuwe jobs;
bestaande jobs gebruiken uitsluitend hun immutable contractsnapshot.

`Dispatcher.start` is de enige workselector achter `start_weekendkrant_executor`.
Er blijft één scheduled executor; start en jobophaling zijn aparte tools. De canonieke backendroute is
`POST /executor/start`; `/executor/sherlock/start` blijft een compatibiliteitsalias
naar exact dezelfde dispatcher, zonder eigen selectie of activatiestate.

## Publieke bootstrap (fase 9.5)

`start_weekendkrant_executor()` accepteert uitsluitend een leeg object. Bibib
berekent met zijn eigen klok de logische UTC-occurrence (executor_slot.py) en
interne startoperatie. De bestaande executor_activations.activation_id is tevens
executor_id; er is geen nieuw schema of sessiemodel. Start retourneert alleen
`{"executor_id": "..."}` of `{"executor_id": null}`. De alias accepteert
eveneens geen caller-identiteiten. De selector hieronder blijft intern.

`get_weekendkrant_job(executor_id)` via `POST /executor/job` leest uitsluitend
die duurzame receipt, met immutable input-, rol- en outputcontracten. Hij
dispatcht nooit opnieuw en leest geen deploymentbestanden. Het pakket bevat
executor_id, role, role_contract, input, input_refs, result_ref, output_contract
en snapshotreferenties plus eventuele aanvullende jobvelden. Claim is één object
met job_id, attempt_id, token en lease_until. De token en lease worden uit de
gebonden attempt gelezen; de receipt bevat geen token. Onbekende of ongebonden
identiteiten worden geweigerd, nooit vervangen door ander werk. Een oude claim
kan worden opgehaald maar verleent geen uitvoeringsmachtiging: validate en
write-fencing blijven noodzakelijk.

Finish en abandon zonder operation_id leiden dezelfde terminale operatie-identiteit
af uit job_id/attempt_id. Exacte payloadretry is idempotent; gewijzigde payload of
een wissel van terminale actie conflicteert. Deze route vereist een bestaande
executorbinding en gebruikt dezelfde atomaire JobControl-mutatie, statecommit en
receipts. De expliciete operator-control-plane behoudt zijn eigen operatie-ID.
De cloudexecutor berekent geen tijd, slots of technische IDs.
Het canonieke runtime-artifact is [executor/instructions.md](../executor/instructions.md);
[executor.md](agents/executor.md) beschrijft de infrastructuur en replaygrenzen.

## Deterministische selectie en uitvoerbaarheid

Iedere korte `BEGIN IMMEDIATE`-selectietransactie gebruikt de backendklok na
lockverwerving:

1. Verlopen attempts worden expired, hun jobs blocked. Geen automatische retry.
2. Een bestaande activation/operation-receipt wordt exact gereplayed, ook als de
   policy inmiddels gepauzeerd is. Gewijzigde identiteit conflicteert. Een receipt
   geeft geen nieuwe uitvoeringsbevoegdheid: validate en write-fencing blijven nodig.
3. Voor een nieuwe activatie: pause, blocked/quarantined jobs en de lanegrens
   controleren. Bij weigering wordt duurzaam `claim:null` opgeslagen.
4. Bestaande `ready` jobs worden op oplopend job-ID bekeken. Alleen een
   geregistreerde roladapter met valide persistente opdracht (`ready(job_id)`)
   en vrije rolcapaciteit is uitvoerbaar. Niet-ondersteunde rollen worden overgeslagen.
   Expliciet herstelde jobs vallen onder dezelfde FIFO-prioriteit, vóór productie.
5. Alleen als geen bestaande job uitvoerbaar is, mogen geregistreerde producers
   in expliciete policyvolgorde nieuw werk overwegen. Preparation gebeurt alleen
   voor de eerstvolgende toegelaten producer die daadwerkelijk wordt overwogen,
   buiten de write-transactie. Daarna begint selectie opnieuw onder de write-lock:
   expiry, receipts, admission en bestaand ready werk worden volledig herbeoordeeld.
   Nieuw ready werk gaat dus vóór productie, en een inmiddels bezette of gepauzeerde
   lane levert een duurzame lege receipt op. Replay, onmiddellijke admissionweigering
   en bestaand ready/recovery-werk hebben helemaal geen preparation nodig. Geregistreerd zijn
   `SherlockProducer`, de ready-only `LeonardoProducer` en `KuifjeProducer`. Alleen Sherlock
   produceert automatisch nieuwe jobs. Geen rolrotatie in de dispatcher.
6. De geselecteerde job wordt opnieuw op ready-status, rol en opdracht gecontroleerd,
   atomair geclaimd en aan rolspecifieke execution-state gebonden. De generieke
   receipt, job, attempt en eventuele run worden samen gecommit. Daarna stopt
   selectie, ook als de job later in dezelfde activatie klaar is.

Sherlock behoudt zijn drie topics, immutable assignments/contracts, runbinding en
30-uurs cooldown sinds de recentste echte `sherlock_runs.started_at`, inclusief
legacy en recovery. Alleen nieuwe productie is geremd; ready recovery behoudt
opdracht/topic. Geen claim betekent geen nieuwe run of verbruikte topicrotatie.
`part_offers` worden nergens door de dispatcher gelezen of geconsumeerd.
Leonardo is uitvoerbaar wanneer `LeonardoStore.enqueue` een expliciete immutable
assignment heeft vastgelegd; een losse jobrij zonder assignment volstaat niet.
Zie het [fase-8-statecontract](leonardo-state.md). Er is geen automatische
Leonardo-productie uit offers.

## Harde grenzen en pause

Schema 10 bevat één persistente `dispatcher_policy`-rij:

| Veld | Default | Betekenis |
| --- | --- | --- |
| `paused` | `0` | `1` verhindert iedere nieuwe intelligente claim |
| `max_running` | `1` | Globale bovengrens running jobs plus running legacy Sherlock-runs, configureerbaar 1..64 |

Aanvullend geldt maximaal één running job per rol. Een running legacy Sherlock-run
bezet een globale plaats én blokkeert Sherlock. Iedere blocked job blokkeert
conservatief de hele lane, ook wanneer de globale grens wordt verhoogd.
Expiry verandert running dus niet in vrije capaciteit: quarantaine blijft een fence.
Dezelfde admissionregels gelden voor een nieuwe expliciete `/jobs/claim`.
De lage `JobStore`-primitieven zijn interne storage-API, geen schedulerinterface.
Verhoog de default niet zonder afzonderlijk beleid en bewijs; deze fase bevat
geen empirisch capaciteitsbeleid en voegt geen scheduler toe.

Operatorvoorbeelden op de productiehost, pas bij bewuste invoering:

```bash
sqlite3 /home/weekendkrant/weekendkrant.sqlite3 'UPDATE dispatcher_policy SET paused=1 WHERE id=1;'
sqlite3 /home/weekendkrant/weekendkrant.sqlite3 'SELECT * FROM dispatcher_policy;'
sqlite3 /home/weekendkrant/weekendkrant.sqlite3 'UPDATE dispatcher_policy SET paused=0 WHERE id=1;'
```

Pause is de kill switch voor **nieuwe starts**, geen proceskill of intrekking van
bestaande geldige claims. Running werk kan validate, schrijven en finish uitvoeren.
Receipts en audit worden niet verwijderd. Voor onmiddellijke operationele stop
van bestaand werk moet de operator ook de executor stoppen en effecten onderzoeken;
expiry/uncertain blokkeert, expliciete recovery met bewijs bepaalt retry of afsluiting.
Recovery blijft tijdens pause mogelijk, maar een herstelde ready job wordt pas na
unpause opnieuw gestart. Een leeg gepauzeerd slot blijft bij replay leeg; een latere
activatie evalueert de nieuwe policy. Geen restart nodig voor een policywijziging.

## Algemene activatiestate en uitbreidingscontract

Additieve migratie 10 maakt `executor_activations`, met dezelfde stabiele IDs,
job-/attemptbinding en immutable audittriggers. Alle schema-9 `sherlock_activations`
worden gekopieerd; oude receipts krijgen hun oorspronkelijke immutable
contractteksten mee. Oude tabellen/gegevens blijven intact. Nieuwe receipts bevatten
het volledige rolantwoord zonder token; replay herstelt alleen de token uit
`job_attempts`, zonder adapter- of deploymentbestanden nodig te hebben.
De control-plane deelt de operatie- en activatienamespace met deze algemene tabel.
Leases, claimtokens en fencing blijven generiek. Fase 8 voegt voor Leonardo
atomair gevalideerde statefinish toe en weigert losse recovery naar succeeded.

Een toekomstige rol registreert een adapter bij `Dispatcher`:
`role`, `prepare()` (begrensde deploymentinput tussen selectietransacties), `ready(job_id)`
(valide persistente opdracht), `produce(now, prepared)` (job-ID of `None`) en
`bind(job_id, claim, now)` (volledig begrensd executioncontract). Selectie, claims,
receipts en activation-ID-logica blijven generiek. Adapterwerk onder de lock is
uitsluitend lokale state, zonder netwerk, modelwerk of filesystem-I/O.
Prepared input wordt alleen binnen deze startcall per producer hergebruikt; geen
claim of productie is vóór preparation gereserveerd. Een preparationfout bevestigt
geen activationreceipt; dezelfde operatie kan opnieuw worden geprobeerd.
`produce()` die `None` teruggeeft maakt geen opdracht of side effects aan.
Rolopdrachten en contracten moeten immutable en concreet zijn vóór uitvoering.

De scheduled executor blijft daarbij strikt rolagnostisch: hij mag geen
geregistreerde rollen opsommen en geen rolspecifieke tools, inputvelden,
workflowstappen, outputstate of finishpayloads definiëren. `bind()` en de
persistente contractsnapshot moeten samen voldoende informatie leveren om de
geclaimde rol volledig uit te voeren. Een nieuwe of gewijzigde rol vereist dus
geen wijziging aan de scheduled executor zolang het generieke executorprotocol
ongewijzigd blijft. Rolkennis hoort in producer/adapter, immutable assignment en
rol-/outputcontract, niet in de gemeenschappelijke executorinstructie.

Het interne dispatchantwoord (opgeslagen zonder token) bevat de claimvelden, `role`, `input`, `input_refs`,
`role_contract_ref`, `role_contract`, `output_contract_ref`, `output_contract` en
`result_ref`. `run_id` is een optioneel rolspecifiek veld. De jobophaaltool transporteert een begrensde rolnaam en objectinput zonder rolspecifieke vertakkingen. Dit maakt andere rollen transporteerbaar, maar autoriseert
geen nieuwe productierol. Alleen de backendregistry bepaalt uitvoerbaarheid.

## Tests en operationele grenzen

De Python-suite test generieke rolselectie/replay zonder Sherlock-state, FIFO vóór
productie, één job per activatie, persistente pause, running/blocked/expiry-fences,
configureerbare globale en seriële rolgrenzen, schema-9-replay en behoud van audit.
Sherlock-tests behouden cooldowngrenzen, recovery, fencing, gelijktijdige starts,
receiptrollback en echte procescrashes vóór/na commit. De systeemtest bewijst de
lokale ingress→claim→source/fiche→finish→materialisatieketen. Pluginchecks testen
het algemene contract en de echte developmentbridge met verloren antwoorden.
Geen van deze tests bewijst productie of Sites-deployment. De nog open fase-5-gate
voor één echte inhoudelijke Sherlock-productieketen blijft open.

Lokale validatie voor deze implementatie: 296 Python-tests groen op Python 3.12,
waaronder de 3 systeemtests; 38 JavaScript-pluginchecks groen op Node 24 en de
aparte bridge/backend-developmenttest groen. Migratie-10-rollback en schema-9-
receiptreplay zijn onderdeel van de dispatcherchecks. Geen productiesmoke uitgevoerd.

Regressievalidatie van lazy preparation: ready Sherlock-recovery en replay met
falende producer-preparation, duurzame pause/running/blocked-weigering zonder
preparation en gelijktijdige statewijzigingen tijdens unlocked preparation
(ready-first, admission en replay van een inmiddels bevestigde activatie).


## Fase 12: missies als ready werk

Leonardo-reevaluation kan met nul nieuwe parts expliciet worden klaargezet.
Een succesvolle Leonardo-finish slaat 1..4 aparte immutable missies voor
hetzelfde topic samen met precies één ready Kuifje-job atomair op; nul missies
levert nul jobs. Een job is één run, missies zijn inhoudelijke subtaken.
Eén activatie claimt maximaal één job, ook wanneer die meerdere missies bevat.
KuifjeProducer bindt uitsluitend bestaande
frozen opdrachten; alle selectie-, admission-, lease- en herstelregels hierboven
blijven generiek. Geen automatische reevaluation of nieuwe scheduler.
Zie het [fase-12-contract en operatorpad](phase-12-kuifje.md).

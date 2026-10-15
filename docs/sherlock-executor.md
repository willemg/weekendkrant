# Fase 5: Sherlock via een generieke executor

## Status en scope

De repository implementeert de eerste Sherlock-jobproducent en de generieke
executorinstructie voor één uurlijkse scheduler. Productie-invoering, werkelijke
schedulercontext en een nieuwe deployment-smoke zijn afzonderlijke open stappen.
Sherlock blijft gepauzeerd zolang de operator hem niet bewust opnieuw activeert.
Er is geen algemene dispatcher, andere rol, extra scheduler of modelcall op bibib.

## Eén atomaire start

`start_weekendkrant_executor({operation_id, activation_id})` gebruikt
`POST /executor/sherlock/start`. Beide IDs zijn niet-lege tekst, maximaal 128
tekens. De bridge verzint geen identiteit. De [executorinstructie](agents/executor.md)
legt de concrete occurrencebinding en het gedrag bij ontbrekende context vast.
De MCP-caller is geauthenticeerd, maar zijn occurrence-ID is geen platformattest.

Onder één korte `BEGIN IMMEDIATE`-transactie, met backendklok na lockverwerving:

1. Zet verlopen attempts in quarantaine. Een running of blocked Sherlock-job
   blokkeert nieuwe productie. Een nog running legacy-run blokkeert eveneens;
   die wordt niet stilzwijgend overgenomen of gesloten.
2. Replay een eerder bevestigde activatie exact, of leg bij bezette baan
   `claim:null` vast. Zo'n lege activatie krijgt ook later geen opdracht.
3. Neem eerst een expliciet na reconciliatie ready gemaakte Sherlock-job terug,
   of maak één nieuwe opdracht voor het volgende topic na de laatste run.
   De rotatie blijft 1 → 2 → 3 → 1, inclusief continuïteit met legacy-runs.
4. Maak job, claim/attempt, run en immutable run→job/attempt-binding samen aan.
   Iedere recovery-attempt krijgt een nieuwe run; de job en het topic blijven
   gelijk. Een oude run wordt nooit heropend.
5. Commit de activatiereceipt samen met alle state. Een exception of crash vóór
   commit laat niets half achter; na commit geeft retry dezelfde identiteit.

De activatie is globaal enkelvoudig over deze adapter en generieke claim heen.
Een andere operation_id bij dezelfde activation_id geeft conflict, evenals
hergebruik van een operation_id uit de generieke control-plane. Exacte startreplay
blijft de oorspronkelijke ontvangstbevestiging, ook na finish of expiry; valideer
vóór werk. Tokens staan alleen in job_attempts en de transportrespons, niet in
activatie-audit. De compacte receipt bewaart contractreferenties; de response
wordt bij replay uit dezelfde immutable snapshots hersteld, zonder contractteksten
per activatie te dupliceren. Een lege start verbruikt geen job of topicrotatie.

## Concrete context en contracten

De response bevat job_id, attempt_id, token, lease_until, role, run_id,
`input={topic,date}`, input_refs, role_contract_ref met role_contract,
output_contract_ref met output_contract, en result_ref. `date` is de lokale
Europe/Brussels-datum bij productie; het fichecontract blijft de actuele lokale
publicatiedatum gebruiken als een herstelrun later wordt uitgevoerd.

Input en rol-/outputcontracten worden als inhoud met SHA-256-referentie opgeslagen
in `sherlock_contracts`. Jobreferenties verwijzen naar deze werkelijke immutable
snapshots. Een latere repositorywijziging verandert lopende jobs of startreplays
niet; recovery gebruikt de oorspronkelijke opdracht en contracten. File-IO en
hashes van rol-/outputbestanden gebeuren vóór de write-transactie; alleen de
kleine toegewezen topic/datum-snapshot wordt onder de lock gehasht. De contracten zijn ieder
maximaal 65536 tekens. De huidige roltekst bewaart topiccatalogus, Nederlandstalige
scouting, bronfiltering, 20-bronnenondergrens/30+-richtwaarde, batches van maximaal
15 onderliggende calls en het bestaande begrensde experimentele safety-retrybeleid.

## Fencing van bron- en fichewrites

`record_sherlock_source` en `submit_weekendkrant_fiche` aanvaarden aanvullend
`claim={job_id,attempt_id,token}`. Voor job-backed runs is dit verplicht.
Runbinding, job/attemptstatus, token en lease worden onder dezelfde write-lock
gecontroleerd als de bron- of queue-insert. Een eerdere succesvolle validate
omzeilt deze controle niet. Vervalste, late of oude claims schrijven niets.
Filtering blijft read-only en gebruikt de bestaande canonicalisatie/deduplicatie.

`sherlock_sources.run_id` en `sherlock_fiches.run_id` verbinden bronregistraties
en queue-items via `sherlock_job_runs` met de exacte job en attempt. De bestaande
consumentenpayload bevat alleen schema_version, topic, date en content;
claim/runmetadata blijft erbuiten. Ariadnes materialisatiecontract verandert niet.
Fichepublicatie blijft niet-idempotent. Bij verloren publicatieantwoord wordt
niet blind opnieuw gepubliceerd; uncertain/abandon blokkeert voor operatoronderzoek.
Ook bronregistratie wordt niet tot een heruitvoeringsprotocol omgebouwd.

Generieke finish accepteert voor een Sherlock-attempt alleen de geleverde
`sherlock-run:<run_id>` als enige outputref. De daadwerkelijke run is het bestaande
resultaatartifact, ook bij lege oogst. Finish sluit attempt, job, run en receipt
atomair. succeeded correspondeert met run completed; failed/uncertain/abandon met
run failed. De backend bewijst de registratie en binding, geen inhoudelijke
waarheid of volledigheid van de scout. Exacte finishreplay voert niets opnieuw uit.
Expiry blokkeert de job; trusted reconciliatie sluit de oude run met een eigen
bewijsreferentie af. Ook trusted recovery naar `succeeded` vereist exact
`output_refs=["sherlock-run:<run_id>"]` voor de gekoppelde attempt. Job, recovery,
runstatus en operation-receipt worden atomair bevestigd: de run wordt `completed`,
ook als uncertain/abandon hem eerder `failed` maakte. Recovery naar `failed`
sluit de run als `failed`; de oude attempt blijft in alle gevallen immutable.
Exacte operation-ID-replay geeft alleen de bestaande bevestiging terug.
Alleen retry na bewezen stop en veilige effecten maakt een
nieuwe attempt op een latere activatie mogelijk.

De legacy-tools blijven beschikbaar voor reeds bestaande legacy-runs. Zodra de
nieuwe adapter een eerste assignment heeft gemaakt, weigert legacy-runstart
nieuwe runs. Legacy-finish en claimloze writes kunnen geen job-backed run muteren.
Ook volledig ongekoppelde fiche-ingress wordt vanaf die eerste assignment
geweigerd, zodat weglaten van run/claim de fencing niet omzeilt. Dat voorkomt
twee naast elkaar werkende aansturingspaden. Er is geen automatische
terugmigratie naar legacy na de eerste nieuwe job.

## Testen en operationele invoering

De Python-unit-/integratietests en proces-/HTTP-systeemgate blijven Node-vrij:

```bash
./start_tests.sh
TIKTOKEN_CACHE_DIR=/home/weekendkrant/.cache/tiktoken .venv/bin/python -m unittest discover -s tests -p 'test_system_e2e.py' -v
```

De systeemgate omvat ook start → bronregistratie → fiche-ingress → finish →
SQLite → afzonderlijk Ariadne-proces → part/revision → processed, met exacte
provenance en herhaalde lege consumptie zonder dubbel materiaal. De afzonderlijke
plugin-developmenttest bewijst JS-brug → HTTP → SQLite, inclusief verloren
start-/finishantwoorden. Beide zijn geïsoleerd en bewijzen geen echte deployment.

Na review/merge volgt een bewuste invoering:

1. Houd de enige bestaande scheduler gepauzeerd en bevestig dat er geen executor
   meer bezig is. Inspecteer eventueel achtergelaten legacy-running runs; sluit
   ze alleen op basis van werkelijke operatorcontrole af. Geen blinde SQL-cleanup.
2. Werk backendcode en centrale migraties bij naar schema 9, draai de volledige
   Python-suite en systeemgate op bibib en herstart ingress. Geen Node op bibib.
3. Bouw/importeer/publiceer de Sites-plugin volgens
   [plugin-deployment](plugin-deployment.md). De plugin krijgt één extra tool;
   dit is een afzonderlijke deployment na de backendupgrade.
4. Vervang de instructie van uitsluitend de bestaande scheduler door
   [executor.md](agents/executor.md). Controleer met echte taakcontext de stabiele
   occurrence-ID of het oorspronkelijke geplande UTC-uurslot. Als die context
   ontbreekt, blijft de taak uit en wordt eerst de adapter aangepast. Het bestand
   alleen bewijst geen actieve instructiesync.
5. Doe één begeleide echte Sherlock-job met claimvalidatie, gekoppelde bronnen en
   legitieme fichepublicatie. Noteer activation/job/attempt/run/queue-ID en finish,
   zonder token, en voer de bestaande complementaire deployment-smoke uit.
6. Activeer de ene uurlijkse scheduler pas wanneer de operator daarvoor kiest.
   De huidige pauze wegens ontwikkelbudget blijft tot dat moment behouden.

Bij problemen: scheduler uit, geen extra activaties en geen blind opnieuw uitvoeren.
Onderzoek ontvangen output en geblokkeerde attempts. Herstel via het bestaande
apart geauthenticeerde reconciliatieprotocol. Schema/audit blijven behouden;
geen downgrade naar een oudere backend die schema 9 niet kent.

## Operationele controle van 15 oktober 2026

De operator bevestigt dat PR #49 is gemerged, backend/schema 9 op bibib is
ingevoerd en de actuele Sites-plugin is gekopieerd en gepubliceerd; in een nieuwe
ChatGPT-context zijn alle tien tools zichtbaar, inclusief
`start_weekendkrant_executor`. Dit is aangeleverd deploymentbewijs, geen in deze
controle uitgevoerde persistente fiche-smoke.

De bestaande taak `6a9e57a40ecc819181c758ccc090d297` heette bij inspectie
`Sherlock Experimental Scout`, was gepauzeerd en bevatte de legacy-instructies
met `start_sherlock_run` en `finish_sherlock_run`. Via Automations is dezelfde
taak hernoemd naar `Weekendkrant Executor 1` en is de volledige prompt vervangen
door de inhoud van `docs/agents/executor.md` (blob
`644cdea7a45a02a62c06f9a1b9fd0ba9e50d2587`). De update bevestigt
`is_enabled=false`; rooster en taakidentiteit zijn behouden.

Beschikbare metadata: vaste taak-ID/naam, Europe/Brussels, VEVENT met
`DTSTART:20260926T112223Z` en
`RRULE:FREQ=HOURLY;INTERVAL=1;BYMINUTE=0`, en
`last_run_time=2026-10-15T12:04:25.925787+00:00`.
Dit laatste is een werkelijke starttijd, geen bewezen oorspronkelijk gepland
occurrencetijdstip. De inspectie-API levert geen native occurrence-ID,
per-uitvoering `scheduled_for` of retrybinding. Dat bewijst niet dat de
uitvoeringscontext die nooit kan bevatten, maar levert de vereiste gate niet.
Het rooster en de huidige klok reconstrueren geen betrouwbare retry-identiteit.

De taak blijft daarom gepauzeerd. Er is geen executorstart, job of proefpublicatie
uitgevoerd. Beide operationele fase-5-checkboxes blijven open: de persistente
deployment-smoke en de begeleide scheduled job zijn nog niet bewezen.

Minimale adaptervoorwaarde: geef aan elke uitvoering een native stabiele
occurrence-ID of het oorspronkelijke geplande UTC-tijdstip mee en bewaar die
waarde ongewijzigd bij retries. Bind de fallback aan
`weekendkrant:scheduler-1:<gepland-UTC-uurslot>`. Controleer deze injectie en
retrybinding in echte uitvoeringscontext vóór een starttoolcall. Een prompt kan
ontbrekende platformmetadata niet zelf leveren. De beschikbare `run_now`-actie
vereist een ingeschakelde taak en biedt geen parameter voor occurrencecontext;
zij is daarom niet gebruikt.

Na die controle moet de operator één begeleide scheduled job laten uitvoeren en
activation_id, job_id, attempt_id, run_id, topic, result_ref, eventuele
queue_item_ids, bevestigde finish en consistente persistente job/runstate
vastleggen, zonder claimtoken. Bij onzekere effecten geldt het bestaande
uncertain/abandon/reconciliatiecontract. Pas met dit bewijs kunnen de gates
worden gesloten; reguliere heractivering blijft een afzonderlijke keuze.

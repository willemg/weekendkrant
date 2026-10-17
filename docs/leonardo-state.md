# Leonardo-state v1, fase-8-slice

Zie de [runtimecontractgrens en begrippen](roles.md#runtimecontracten-fase-85):
`roles/*.md` zijn de canonieke versioned runtime-artifacts voor nieuwe jobs;
bestaande jobs gebruiken uitsluitend hun immutable contractsnapshot.

Deze slice implementeert expliciete dossier- en jobaanmaak in de Python-backend,
ready-dispatch via de bestaande dispatcher en statefinish via de bestaande
HTTP/MCP-tool. Geen permanente worker, nieuwe scheduler, automatische
jobproductie uit offers, model-API-call, missie-uitvoering of fase-9-proefcyclus.
Voor reevaluation en afzonderlijke immutable missies geldt aanvullend het
[fase-12-contract](phase-12-kuifje.md), dat de eerdere uitsluitingen van
missies hieronder vervangt. Leonardo-state bevat nooit missies.

Een topic is geen dossier: de aanroeper kiest expliciet een inhoudelijke
`dossier_id`. De eerste slice begrenst een dossier tot één topic.

## Opslag en identiteit

Schema 11 introduceerde vier append-only tabellen: `leonardo_dossiers`,
`leonardo_assignments`, `leonardo_assignment_parts`, `leonardo_states`.
Update, delete en replace worden door triggers geweigerd. Bestaande data krijgt
geen automatische dossierindeling. De huidige state is de hoogste opgeslagen
versie van het dossier; er bestaat geen tweede mutable current-statepointer.

Een dossier begint zonder state (basisversie 0). Iedere succesvolle job voegt
precies één versie toe met predecessor, job, attempt, canonieke JSON-bytes,
SHA-256, vaste `cl100k_base`-tokenmeting en UTC-timestamp. De tabel heeft unieke
job-/attemptidentiteiten en een foreign key naar de vorige stateversie.
De opgeslagen canonieke JSON is de bron van waarheid, geen modelgeheugen.

`LeonardoStore.create_dossier(id, topic)` is idempotent voor dezelfde identiteit
met hetzelfde topic. `enqueue(operation_id, dossier_id, base_version,
[[part_id, revision], ...])` maakt expliciet één job. Dezelfde enqueue-identiteit
met exact dezelfde opdracht retourneert dezelfde job; gewijzigde argumenten
worden geweigerd. Dit is een lokale backendinterface, geen nieuwe publieke
automatische producer of MCP-aanmaaktool.

## Begrensde inputsnapshot

Nieuwe enqueue leest `roles/leonardo.md` en `roles/leonardo-output.md` als
begrensde exacte UTF-8-contracten. Een identieke enqueue-retry retourneert de
bestaande job zonder role-file-I/O. De job-outputref hasht de exacte opgeslagen
outputtekst, de rolref hasht bij bind uitsluitend de persistente roltekst.
Historische assignments en refs worden niet gemigreerd of herschreven.

Een gewone assignment bevriest de vorige state, 1–32 expliciet gekozen revisies,
exact gereconstrueerde brontekst en hashes, rolcontract en outputcontract in
SQLite. Revisies moeten bij het dossiertopic horen. De normale provenance en
`revision_storage.reconstruct` controleren bytes, bronvolgorde, hashes en tokens.
Foreign keys naar de partrevisies blijven behouden. Schema 12 verruimt het
snapshot tot maximaal 1.048.576 `cl100k_base`-tokens en 8 MiB UTF-8, inclusief
beide contracten. Dit zijn lokale technische allocatie-/serialisatiegrenzen,
geen economisch optimum en geen gemeten providercontextlimiet.
Dit is een backendpayloadgrens, geen bewijs over een toekomstige provider-
messagewrapper of modeltokenizer; een echte modeladapter moet de volledige
request nog meten volgens het modelcontract.

Reconstructie en tokenmeting vinden vóór de schrijflock plaats. Onder de korte
finale lock worden basisversie en afwezigheid van ready/running/blocked werk voor
hetzelfde dossier opnieuw gecontroleerd. Er kan slechts één onafgeronde
assignment per dossier ontstaan. De assignment en generieke job ontstaan atomair.

De `LeonardoProducer` is een ready-only adapter: `produce` creëert niets.
Bestaand ready werk blijft volgens fase 7 vóór nieuwe Sherlock-productie komen.
Een replay of recovery leest zijn contractsnapshot uit SQLite en heeft geen
actuele rolcontractfiles nodig. Iedere activatie krijgt de volledige relevante
persistente state opnieuw mee.

## Output en commit

`finish_weekendkrant_job` krijgt voor Leonardo `status=succeeded`,
`output_refs=[result_ref]` en `leonardo_state` als JSON-object. De backend eist:

- schema v1, exact dossier, volgende versie en juiste basisversie;
- afzonderlijke hypotheses, claims, onzekerheden en open vragen;
- stabiele item-IDs, tekst en expliciete bronreferenties;
- claims onderscheiden `source_fact` en `inference`, met afzonderlijke
  ondersteuning en tegenbewijs; een bronfeit vereist ondersteuning;
- `processed_refs` is exact de unie van vorige verwerkte revisies en deze input;
- itemreferenties verwijzen naar verwerkte revisies of naar queuefiches die
  aantoonbaar lid zijn van minstens één van die exacte immutable revisies;
- maximaal 64 items per categorie, 256 verwerkte revisies, 4.000 vaste
  v1-tokens en 32.768 UTF-8 bytes voor de volledige canonieke outputstate.

Een rolling samenvatting wordt geen primaire bron. De backend valideert vorm,
identiteit, omvang en provenance, niet de inhoudelijke waarheid van claims.
Er is geen automatische truncatie of compressielus. Het cumulatieve maximum
van 256 revisies is een zichtbare v1-grens: overschrijding vereist later een
expliciet nieuw contract/archiveringsbeleid en verwijdert nu niets.

Fase 11 onderscheidt twee lagen: `processed_refs` is coarse-grained input
provenance op immutable partrevision-niveau; `refs`, `support` en
`counterevidence` zijn fine-grained inhoudelijke provenance. Een item mag een
verwerkte `part:<id>:<revision>` en/of `queue:<id>` gebruiken. Queue-membership
wordt server-side bewezen via `revision_sources` en `source_archive`, uitsluitend
binnen de transitieve grens van de daadwerkelijk verwerkte immutable revisies.
Het bestaan van een queue-ID, dezelfde topic of membership in een andere
(actieve) revision is onvoldoende. De mutable ingressqueue en actieve
partpointer worden niet geraadpleegd. Geen fuzzy tekstmatching, nieuwe tabel of
dubbele persistente mapping; historische revisies blijven zonder fysieke file
bruikbaar. Bestaande partrefs en historische states blijven behouden.

Het nieuwe outputcontract begint met `leonardo-output-v2:`; de JSON-state blijft
schema v1, met dezelfde velden en omvangsgrenzen. Alleen assignments met deze
expliciete versie in hun immutable outputcontract mogen queue-itemrefs gebruiken.
Oude contractsnapshots blijven part-only, ook na een backendupdate. De exacte
`processed_refs`-unie wordt vóór de membershipcontrole gecontroleerd, binnen
het bestaande gefencete atomaire finishpad. Een model kan zijn inputgrens dus
niet uitbreiden door extra processed refs mee te sturen. Zie
[fase 11](phase-11-leonardo-provenance.md) voor bewijs en compatibiliteit.

De bestaande claim-/leasecontrole en stateversie-CAS gebeuren onder dezelfde
lock als jobfinish, operation receipt en state-insert. Een validatiefout rolt de
hele mutatie terug; vorige state en running job blijven behouden. De executor
kan daarna zichtbaar failed/uncertain melden. Failed/uncertain vereisen
`output_refs=[]` en geen `leonardo_state`; abandon bewaart eveneens lege outputs. Geen van deze uitkomsten maakt state of bewaart
een toekomstige state-outputref.
Verlopen attempts blijven geblokkeerd; oude claims mogen niets committen.

Verloren finishantwoord: herhaal dezelfde operation-id met exact dezelfde
argumenten. De receipt retourneert het bevestigde resultaat zonder nieuwe
state. Ook een nieuwe operation-id met dezelfde claim/status/output/error en
exact dezelfde reeds bevestigde dossierstate is een no-op. Dossier, versie,
predecessor, job/attempt, canonieke content, hash en tokenmeting moeten gelijk
blijven, ook als inmiddels nieuwere state bestaat. Een inhoudelijke afwijking
blijft een conflict. Recovery gebruikt het bestaande operatorpad met bewijs
van gestopte uitvoering en gecontroleerde effecten: retry of failed. Losse recovery naar
succeeded is voor Leonardo verboden: succes en state moeten samen ontstaan.
Een retry krijgt dezelfde immutable input en een nieuwe gefencete attempt.

## Uitgestelde scope en bevinding na de eerste productieproef

De eerste echte scheduled Leonardo-job is op 16 oktober 2026 succesvol afgerond.
De assignment mat lokaal 23.665 `cl100k_base`-inputtokens; state v1 mat 1.844
tokens. Een eerdere attempt expireerde en de succesvolle tweede attempt schreef de
state via het bestaande fenced finishpad. Deze lokale tellingen zijn geen
providerusage of productkost.

## Historical recall, fase 9.6

De oorspronkelijke 35K-grens was een arbitraire eerste cognitieve
chunkinghypothese: geef Leonardo niet zoveel nieuw, onbekend bronmateriaal
tegelijk dat hij zijn overzicht verliest. Het was geen kostenbudget. Fase 9.6
laat die hypothese bewust los om empirisch te ontdekken hoeveel nieuw materiaal
hij in één run goed structureel kan verwerken. De 1.048.576-token/8-MiB-grens is
uitsluitend een technische noodrem, evenmin een optimale behapbare brok.

`recall_weekendkrant_part(job_id, attempt_id, token, ref, recall_id)` is de
read-only inhoudsbrug binnen dezelfde lopende Leonardo-job. HTTP:
`POST /jobs/leonardo-recall`. De request heeft exact die vijf velden;
`recall_id` is een niet-lege attempt-lokale identiteit van maximaal 128 tekens.
De response bevat uitsluitend `ref`, `sha256`, `content`, `bytes`, `tokens`
(MCP voegt `status:success` toe). Bytes en vaste `cl100k_base`-tokens meten exact
de UTF-8-brontekst in `content`, niet de JSON-wrapper of providerberichten.

De backend autoriseert uitsluitend de unie van de vorige `processed_refs` en
de nieuwe parts uit de immutable assignment. Een nieuw aangeboden ref mag dus
ook opnieuw gelezen worden. Dezelfde topic of een ander dossier is op zichzelf
nooit voldoende autorisatie. Geen lookup op willekeurige part/revisionparen,
semantische selectie, nieuw dossier, nieuwe job of scheduleractivatie.

Vóór reconstructie én onder de korte finale auditlock worden job, attempt,
token, rol, executorbinding, running-status, laatste attempt en actuele lease
gecontroleerd. Een oude receipt verleent geen leesrecht. Recall voert geen
expirysweep uit en verandert geen job-, dossierstate- of bronprovenance.
`revision_storage.reconstruct()` verifieert bestaande membership, source_archive,
hashes en tokenaudit, ook zonder redundant revisiebestand. Reconstructie en
meting gebeuren buiten de schrijflock. De bestaande centrale migratieketen
verhoogt schema 11 naar 12 met behoud van alle assignments, states, foreign keys
en immutable triggers; uitsluitend de oude input-CHECK wordt verruimd en de
append-only tabel `leonardo_recalls` wordt toegevoegd.

Een geslaagde logische read krijgt dossier/job/attempt, recall_id, ref,
part/revision, oplopende audit-ID, UTC-timestamp, bytes en tokens. Bronbytes en
claimtokens worden niet gekopieerd naar de audit. Dezelfde attempt/recall_id
met dezelfde ref herhaalt de exacte reconstructie zonder tweede auditrecord;
een gewijzigde ref conflicteert. Iedere retry controleert opnieuw actuele
bevoegdheid, ook na een eerder bevestigd antwoord. Bewuste nieuwe herlezing
krijgt een nieuwe recall_id en telt opnieuw. Audit betekent dat de backend de
response heeft voorbereid, geen bewijs van modelontvangst. Fouten blijven
zichtbaar via de bestaande received/finished/HTTP-statuslogging, met gevalideerde
job-/attemptidentiteiten en ref, zonder payload of token te loggen.

Per attempt geldt dezelfde technische fail-safe voor startinput plus cumulatieve
unieke recallcontext: 1.048.576 lokale tokens en 8 MiB bron-/snapshotbytes.
Een retry van dezelfde logische read telt niet dubbel; eventuele herhaalde
transport-/modelconsumptie is onbekend. De bytegrens begrenst geheugen en
serialisatie, de tokengrens beschermt ook tegen zeer tokenrijke payloads.
De tokengrens ligt ruim boven één part en omvat de orde van grootte van de
bestaande maximale startbundel (32 × circa 30K), plus ruimte voor compact geheugen.
8 MiB is een expliciet eindig lokaal serialisatiebudget op de Pi-host, geen
benchmarkclaim over piekgeheugen. Beide zijn ruime noodremmen tijdens karakterisering, geen
bewezen capaciteit van het scheduled model. De bestaande 32-parts-per-assignment-
en circa-30K-partgrenzen blijven gelden. Overschrijding weigert zichtbaar zonder
truncatie, nieuwe state of recallrecord. De 4K/32.768-byte outputgrens blijft.

Rolling state is een verliesgevende structurele kenniskaart. Items mogen
samengevoegd, herschreven, samengevat of verwijderd worden; processed_refs blijven
provenance. Modelstate wordt geen primaire bron. Historie wordt gericht herlezen,
nooit integraal vooraf geladen. Nieuwe jobs bevriezen het bijgewerkte Leonardo-
rolcontract; bestaande jobs behouden hun oude snapshot. Einstein-analyse blijft uitgesloten. Fase 12 voegt afzonderlijke missievoorstellen
en Kuifje-jobs toe, zonder missies in dossierstate op te slaan.

`leonardo_operator.py ... inspect --job ID --compact` toont in `context_usage`
ook `new_part_count`, `new_part_tokens`, `new_part_bytes` en `new_parts`: een lijst
in assignmentvolgorde met `ref`, `tokens` en `bytes` per aangeboden part. De
metingen tellen uitsluitend de exacte UTF-8-brontekst uit het immutable snapshot,
zonder state, contracten of JSON-wrapper. "Nieuw" betekent hier aangeboden in deze
assignment, geen semantische nieuwheid of deduplicatie van overlappende revisies.
`previous_state_tokens` meet de canonieke JSON van de vorige snapshotstate
(0 zonder vorige state). Deze deterministisch afleidbare inspectiemetingen
vereisen geen schemawijziging, nieuwe auditopslag of reconstructie van bronfiles.
De som van afzonderlijk getokeniseerde componenten hoeft door tokenisatiegrenzen
en JSON-escaping niet gelijk te zijn aan de tokenmeting van de totale snapshot.

Daarnaast blijven totale `start_input_tokens`,
recallvolgorde, bytes/tokens per read, cumulatieve recalltokens/-bytes en eventuele
state-tokens afzonderlijk per attempt beschikbaar, inclusief expired/failed attempts.
De volledige inspectie bevat dezelfde `context_usage`-sectie. Werkelijke
providerusage en geldkost blijven onbekend (`provider_usage:null`), nooit nul
op basis van een mislukte attempt en nooit afgeleid uit lokale tokenmetingen.
Deze implementatie heeft lokale testdekking; productie-invoering en meerdere
karakteriseringsruns blijven afzonderlijke operationele stappen.

Ten tijde van fase 9.6 volgden missievoorstellen en -administratie nog later.
Inmiddels implementeert [fase 12](phase-12-kuifje.md) die keten: Leonardo levert
maximaal vier afzonderlijke missievoorstellen naast de state. Ariadne/backend
valideert en bewaart ze atomair als immutable artifacts en bundelt de missies
van één succesvolle finish binnen hetzelfde topic tot één Kuifje-job/run.
Leonardo spawnt nooit rechtstreeks een andere worker. Expliciete selectie van
een terminale Kuifje-job/attempt levert alle missie-uitkomsten terug als
`research_results`, zonder `processed_refs` uit te breiden.
Dossieroverstijgende synthese, automatische offer-to-jobpolicy, betrouwbare
providerkosten en eindredactionele selectie volgen eveneens afzonderlijk. Ariadne
voert geen semantische dossierkeuze uit.
Voor invoering van recall zijn schema 12, backendherstart en synchronisatie/
publicatie van de MCP-bridge nodig. Het minimale executorcontract verandert niet.

## Eerste fase-9-experiment

De [lokale operatorbrug en proefprocedure](phase-9-trial.md) koppelen expliciet
gekozen bestaande sealed offers aan een bewust gekozen dossier. De brug gebruikt
uitsluitend `LeonardoStore.enqueue()`, inclusief de fase-8.5-contractsnapshot;
zij leest of injecteert zelf geen roltekst. Dispatch en finish blijven ongewijzigd.
Er is geen automatische routing of offerconsumptie. Schema 11, fase-8.5-backend,
Sites-bridge met `leonardo_state` en rolagnostische executor zijn volgens de
operator gedeployd; de eerste echte scheduled Leonardo-proef is hierboven vastgelegd.

# Fase 12: reevaluation en gerichte onderzoeksmissies

Leonardo kan bestaand dossiergeheugen opnieuw evalueren zonder nieuwe bronnen.
Hij levert normale volgende dossierstate en optioneel afzonderlijke
missievoorstellen. **Leonardo-state bevat nooit Kuifje-missies**, ook niet in
hypotheses, claims, uncertainties of open_questions. Vragen zijn redactioneel
geheugen; een concrete missie is aparte immutable runtime-input voor Kuifje.

## Expliciete reevaluation

`LeonardoStore.reevaluate(operation_id, dossier_id, base_version)` gebruikt het
bestaande enqueuepad met `mode=reevaluation`, een bestaande state en precies nul
nieuwe parts. Gewone enqueue behoudt `mode=new_material` en 1–32 parts. Er worden
geen oude revisies opnieuw als nieuw geregistreerd en geen dummy-parts gemaakt.
Het snapshot bevriest state, mode, tokenizer en rol-/outputcontract. Dezelfde
operation_id/opdracht replayt dezelfde job, ook na afronding; een nieuwe
reevaluation vereist een nieuwe operation_id. Bestaande enqueue-identiteiten
voor gewone jobs veranderen niet.

Een succesvolle reevaluation schrijft de normale volgende stateversie met
exact ongewijzigde processed_refs (ook volgorde). De bestaande recall controleert
actuele claimautoriteit en kan de immutable processed revisies gericht herlezen.
Dezelfde pending-dossiergrens, CAS, leases, fencing en technische contextgrenzen
blijven gelden. Er is geen automatische periodieke reevaluation.

## Afzonderlijke missie-artifacts

Nieuwe Leonardo-jobs bevriezen de actuele `roles/leonardo.md` en
`roles/leonardo-output.md` in een machineleesbaar assignmentsnapshot met
`schema_version=2`. Die machineversie ondersteunt queueprovenance en missies,
onafhankelijk van natuurlijke prompttekst. Alleen historische schema-1-assignments
behouden hun frozen prefixsemantiek. Een nieuwe finish kan naast `leonardo_state` een aparte
`kuifje_missions`-lijst bevatten, maximaal vier voorstellen met exact:

| Veld | Betekenis |
| --- | --- |
| question | Concrete onderzoeksvraag, maximaal 8192 tekens |
| rationale | Aanleiding in de bestaande analyse, maximaal 8192 tekens |
| scope | Expliciete begrenzing, maximaal 8192 tekens |
| refs | 1–256 unieke part-/queue-referenties binnen het succesvol gevalideerde processed corpus |

De backend geeft iedere missie `kuifje:<Leonardo-job-id>:<ordinal>` en bindt haar
aan dossier, topic, producerende job en de tegelijk opgeslagen stateversie.
`kuifje_missions` bewaart de canonieke JSON, hash, bytes, tokens, tokenizer en
tijdstip. Deze tabel is een afzonderlijk immutable artifact, volgens het
bestaande SQLite-assignmentpatroon; geen veld in leonardo_states en geen mutable
current mission text. `roles/kuifje.md` is het algemene rolcontract. Het
missie-artifact is de concrete opdracht, geen wijziging aan dat rolcontract.

Provenance mag uitsluitend verwijzen naar het processed corpus dat de nieuwe
Leonardo-outputstate in dezelfde succesvolle finish heeft: vorige frozen
processed_refs plus de immutable parts van de huidige assignment. Queuefiches
zijn geldig wanneer membership in één van die exacte revisies bewezen is via
revision_sources en source_archive. Geen lookup in actuele queue/active_revision,
geen fuzzy tekstkoppeling. Een lacune uit nieuwe input kan onmiddellijk een
missie opleveren. Reevaluation heeft geen nieuwe parts en behoudt dus precies
de vorige corpusgrens. Item-ID's worden niet gebruikt: rolling
items mogen worden samengevoegd/verwijderd. Historische schema-1-assignments behouden hun capabilitygrens: outputprefix
`leonardo-output-v1:` staat alleen parts toe, `leonardo-output-v2:` ook queueprovenance,
en `leonardo-output-v3:` ook missievoorstellen. Deze labels worden uitsluitend voor
legacycompatibiliteit geïnterpreteerd en keren niet terug in actuele rolefiles.

## Atomiciteit en uitvoering

Contractfiles en tokenmeting worden vóór de write-lock voorbereid. Na generieke
claimfencing schrijft dezelfde finish-savepoint de volgende Leonardo-state,
1..4 missie-artifacts, precies één ready Kuifje-job, één frozen
`kuifje_assignments`, de ordered `kuifje_assignment_missions`-mapping en terminale
receipt. Nul missies levert geen Kuifje-job. Alle missies delen mechanisch
dezelfde dossier-, state-, producer- en topicidentiteit. Er is geen bundeling
over verschillende Leonardo-runs. Een fout rolt alles terug; expiryquarantaine
blijft volgens het bestaande controlcontract behouden. Unieke producer/ordinal-
en mission/jobbindingen plus inhoudsvergelijking voorkomen dubbele objecten bij
exacte terminale retries, ook via een andere expliciete operatie-identiteit.
Een gewijzigde terminale request conflicteert. Deploymentcontracten worden bij
replay niet heropend.

De ready-only KuifjeProducer draait via dezelfde dispatcher, FIFO, globale lane,
seriële rolgrens, pause, claims, attempts en executorreceipts. Geen nieuwe tools,
rollenlijst in de executor of scheduler. Het jobpakket bevat het frozen algemene
rolcontract, de ordered `input.missions`-lijst en outputcontract. Recovery hergebruikt dezelfde
missieset/assignment en maakt uitsluitend een nieuwe attempt na operatorbewijs.
Losse claims omzeilen deze binding niet; recovery naar succeeded zonder atomair
gevalideerde output wordt geweigerd.

Kuifje zoekt binnen de opdracht, maximaal 20 inhoudelijk gereviewde bronnen en
5 fiches per missie (de backend handhaaft de fichegrens). Hij maakt geen nieuwe
missies/dossiers en wijzigt geen Leonardo-geheugen. Hij krijgt geen algemene
recallbevoegdheid; vraag, aanleiding en scope moeten zelfstandig bruikbaar zijn.
Succes schrijft één jobresultaat met
`kuifje_result={"mission_results":[{"mission_id":"...","summary":"...","limitations":"..."}]}`
en `result_ref=kuifje-result:job:<job_id>`. Iedere assigned missie komt exact één
keer voor in assignmentvolgorde, zonder vreemde IDs; beide tekstvelden zijn
niet-leeg en maximaal 8192 tekens per missie, ook bij lege oogst. Succes betekent
dat alle missies zijn afgehandeld. De claim wordt opnieuw gevalideerd vóór nieuw
werk na iedere missiegrens en vóór schrijfacties. Failed/uncertain heeft geen outputrefs/resultaat;
de generieke error/attemptaudit bewaart de fout. Reeds gepubliceerde fiches blijven
behouden bij een latere failure, met hun oorspronkelijke producerende attempt.

## Bestaande ficheketen

Kuifje gebruikt dezelfde submit_weekendkrant_fiche en POST /ingress met de
ongewijzigde vier inhoudsvelden schema_version/date/topic/content. mission_id,
fiche_id en claim zijn transportmetadata; run_id is exclusief voor Sherlock.
De ingress stript deze metadata en bewaart de producerbinding apart in
kuifje_fiches: queue-item, Kuifje-job, producerende attempt, expliciete mission_id,
stabiele fiche_id en
payloadhash. De composite foreign key `(job_id,mission_id)` naar de ordered mapping bewijst
het missielidmaatschap. De fichegrens is vijf per `(job_id,mission_id)`.

Actuele lease, token, meest recente attempt, executorbinding en missietopic
worden onder de ingresslock gecontroleerd, ook bij retries. De klok wordt na
lockverwerving gelezen. Dezelfde job/mission_id/fiche_id/payload retourneert dezelfde
queue-ID; een gewijzigde payload conflicteert. Een herstelde attempt kan dezelfde
fiche bevestigen zonder de oorspronkelijke producer te overschrijven. Na
claimverlies mag ook een retry niets meer publiceren.

Ariadne materialiseert deze gewone fiches via source_archive/revision_sources
naar nieuwe immutable partrevisions. De keten is terug te volgen met
revision_sources → kuifje_fiches → kuifje_assignment_missions → kuifje_missions.
Een latere gewone Leonardo-enqueue krijgt expliciet geselecteerde nieuwe
revisies voor het bestaande dossier; fase 12 introduceert geen automatische
inhoudelijke dossierrouter of offerselectie. Kuifje schrijft nooit rechtstreeks
in parts of Leonardo-state.

## Resultaatretour zonder bronfiche

Een operator kan aan gewone enqueue of reevaluate optioneel kuifje_results
meegeven: maximaal zestien expliciete [job_id,attempt_id]-paren. De backend
accepteert uitsluitend de huidige terminale succeeded/failed attempt van een
Kuifje-job uit hetzelfde dossier. De missie moet reeds uit een voor deze
Leonardo-basisversie bestaande state voortkomen. Onbekende, vreemde, lopende,
expired, uncertain of door recovery vervangen attempts worden geweigerd.
Er is geen automatische selectie en geen mutable latest-result-pointer.

Voor succeeded wordt het immutable kuifje_results-record met exact dezelfde
job/attemptbinding gelezen, ook als er nul fiches zijn. Voor een terminale
failed attempt worden status/error uit de bestaande immutable attemptaudit
gebruikt; er wordt geen succesvolle resulttekst verzonnen. De algemene
jobstatus en gesloten attemptstatus moeten overeenkomen. Een via recovery
beëindigde uncertain/expired attempt wordt dus niet als direct failed resultaat
aangeboden.

Eén geselecteerd JOB:ATTEMPT wordt deterministisch in assignmentvolgorde
uitgevouwen naar één `research_results`-item per missie, ook bij failed jobs
(zonder per-missie succes te verzinnen). Het Leonardo-snapshot bevat daarin
mission_id, concrete missie, missiehash,
job/attempt, outcome-ref, status, fout, eventueel resultaat/resultref/hash en
oorspronkelijke tokenaudit. Die volledige aanvullende context wordt samen met
het overige assignment door Ariadne's actuele tokenizer gemeten en immutable
opgeslagen. De selectie maakt deel uit van de enqueue-requestidentiteit; exact
retry replayt hetzelfde snapshot, een gewijzigde selectie conflicteert.
Bestaande enqueue-receipts zonder resultaatselectie behouden hun identiteit.
Geen nieuwe tabel, tool, recallroute of scheduler is nodig.

Deze context is geen primaire bron en verruimt processed_refs of itembronrefs
niet. Leonardo mag de betekenis van lege oogst/beperkingen redactioneel
evalueren in zijn normale geheugen, maar kopieert geen missie-/resultaatobjecten
of operationele administratie naar leonardo_states. De herleidbare keten is:
missie → Kuifje-assignment/job → exact terminal resultaat/attempt → frozen
research_results in de latere Leonardo-assignment. Er ontstaan geen dummy-fiches,
queue-items of partrevisions.

## Eén meetinstrument van Ariadne

ariadne_tokens.py bevat Ariadne's canonieke actuele tokenizerprimitive voor
daily, Leonardo, Kuifje en nieuwe runtimecontext. Dit is een gedeelde lokale
meetlat, geen agent-eigen tokenizer en geen providerusage, verborgen modeltokens
of geldkost. Het historische WEEKENDKRANT-PART-1-contract blijft onafhankelijk:
part_format_v1.py heeft zijn eigen frozen TOKENIZER='cl100k_base' en expliciete
v1-tokenberekening. revision_storage.reconstruct gebruikt uitsluitend die
historische implementatie voor oude bytes/hashes/tokens. Zelfs vervanging van
Ariadne's actuele primitive en herladen van de historische module verandert die
reconstructie niet. Een actuele tokenizerwijziging mag nooit v1 herschrijven.

Reevaluation bewaart tokens in het bestaande assignment en tokenizer-identiteit
in de frozen snapshot; UTF-8 bytes zijn exact uit die immutable tekst afleidbaar.
Missie en Kuifje-assignment bewaren bytes/tokens/tokenizer expliciet; ook het
terminale Kuifje-resultaat wordt zo gemeten. Inspectie blijft compact en lokaal.
De canonieke auditidentiteit is cl100k_base volgens het bestaande partcontract;
een wijziging ervan vereist een expliciet nieuw versiecontract.

## Operatorpad en invoering

Na code-update: voer de centrale database.py-migratie naar schema 14 uit en
herstart de ingressbackend. Synchroniseer/publiceer daarna de Sites-brug met de
nieuwe optionele finish- en fichevelden voordat nieuwe jobs worden uitgevoerd.
Migratie en Sites-publicatie zijn afzonderlijke operationele stappen.

Voor een bewust gekozen bestaand dossier (geen kunstmatig bronmateriaal):

```bash
.venv/bin/python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 \
  dossiers
.venv/bin/python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 \
  reevaluate --dossier DOSSIER --base-version VERSIE --operation-id UNIEKE_OPDRACHT
.venv/bin/python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 \
  inspect --job JOB_ID --compact
.venv/bin/python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 \
  inspect-mission --mission kuifje:JOB_ID:1
# De inspectie levert Kuifje-job en attempt; selecteer bewust het concrete paar:
.venv/bin/python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 \
  reevaluate --dossier DOSSIER --base-version VERSIE --operation-id NIEUWE_OPDRACHT \
  --kuifje-result KUIFJE_JOB:KUIFJE_ATTEMPT
```

De Leonardo-inspectie toont dossier, basisversie, mode, new_part_count=0,
previous_state_tokens, recallaudit per attempt, outputstate-tokens en
mission_count. Missie-inspectie toont identiteit, producerende Leonardo-job,
dossier/stateversie, provenance, bytes/tokens/tokenizer, gekoppelde Kuifje-job,
status, attempt_id, assignmentomvang, mission_count, fiche_count voor deze missie
en job_fiche_count voor de volledige run. Leonardo-contextinspectie
toont ook research_result_count (missie-uitkomsten), selected_kuifje_job_count
(geselecteerde runs), research_result_refs en contexttokens/-bytes. Status leeft op de generieke job,
nooit als mutable tekst in de missie.

## Schema 14 en frozen compatibiliteit

Een job is één run; een missie is een inhoudelijke subtaak en immutable
provenance-artifact, geen schedulingeenheid. Schema 13 legde historisch een
één-op-één-relatie vast. Migratie `014_grouped_kuifje.sql` vervangt die relationele
vorm door job-level assignments en ordered mapping, met unieke missionbinding.
Iedere bestaande job krijgt uitsluitend mappingpositie 1. Bestaande job- en
mission-ID's, snapshotbytes/hashes, metingen, statuses, attempts, receipts, fiches
en resultaten blijven exact behouden. Er worden geen oude ready jobs gebundeld,
opnieuw gesnapshot of opnieuw gepland. Migratie blijft atomair en idempotent.

Frozen Kuifje-schema-1-input behoudt singular `mission`, oude contractbytes,
`kuifje_result={summary,limitations}` en `kuifje-result:<mission_id>`.
Nieuwe schema-2-input gebruikt uitsluitend `missions` en `mission_results`,
ook voor één missie. De snapshotversie bepaalt het resultaatcontract; de plugin
transporteert beide vormen zonder zelf die backendbeslissing te nemen.

## Gerichte validatie

De lokale fast-track karakteriseert grouped productie, per-missie ingress,
volledige ordered resultaten, frozen compatibiliteit, schema-13-retentie,
rollback, fencing en expliciete feedback. De pluginlaag valideert beide
resultaatvormen en de echte MCP → HTTP → SQLite → Ariadne-keten. Gebruik
uitsluitend `./start_tests.sh` en `./start_tests.sh --plugin`; de volledige
suite draait afzonderlijk in CI op de exacte commit.

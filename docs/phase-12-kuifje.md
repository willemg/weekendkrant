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

Nieuwe Leonardo-jobs bevriezen `roles/leonardo.md` v4 en
`roles/leonardo-output.md` v3. Hun finish kan naast `leonardo_state` een aparte
`kuifje_missions`-lijst bevatten, maximaal vier voorstellen met exact:

| Veld | Betekenis |
| --- | --- |
| question | Concrete onderzoeksvraag, maximaal 8192 tekens |
| rationale | Aanleiding in de bestaande analyse, maximaal 8192 tekens |
| scope | Expliciete begrenzing, maximaal 8192 tekens |
| refs | 1–256 unieke part-/queue-referenties binnen het eerder verwerkte corpus |

De backend geeft iedere missie `kuifje:<Leonardo-job-id>:<ordinal>` en bindt haar
aan dossier, topic, producerende job en de tegelijk opgeslagen stateversie.
`kuifje_missions` bewaart de canonieke JSON, hash, bytes, tokens, tokenizer en
tijdstip. Deze tabel is een afzonderlijk immutable artifact, volgens het
bestaande SQLite-assignmentpatroon; geen veld in leonardo_states en geen mutable
current mission text. `roles/kuifje.md` is het algemene rolcontract. Het
missie-artifact is de concrete opdracht, geen wijziging aan dat rolcontract.

Provenance mag uitsluitend verwijzen naar processed_refs uit de **vorige frozen
state**, of queuefiches waarvan membership in die exacte revisies bewezen is via
revision_sources en source_archive. Geen lookup in actuele queue/active_revision,
geen fuzzy tekstkoppeling. Nieuwe input van een gewone Leonardo-run vergroot
niet onmiddellijk de missieautoriteit. Item-ID's worden niet gebruikt: rolling
items mogen worden samengevoegd/verwijderd. Historische v1/v2-outputcontracten
blijven frozen en verlenen geen missiecapability; fase-11-v2-queueprovenance blijft
wel geldig.

## Atomiciteit en uitvoering

Contractfiles en tokenmeting worden vóór de write-lock voorbereid. Na generieke
claimfencing schrijft dezelfde finish-savepoint de volgende Leonardo-state,
missie-artifacts, precies één ready Kuifje-job per missie, frozen
kuifje_assignments en terminale receipt. Een fout rolt alles terug; expiryquarantaine
blijft volgens het bestaande controlcontract behouden. Unieke producer/ordinal-
en mission/jobbindingen plus inhoudsvergelijking voorkomen dubbele objecten bij
exacte terminale retries, ook via een andere expliciete operatie-identiteit.
Een gewijzigde terminale request conflicteert. Deploymentcontracten worden bij
replay niet heropend.

De ready-only KuifjeProducer draait via dezelfde dispatcher, FIFO, globale lane,
seriële rolgrens, pause, claims, attempts en executorreceipts. Geen nieuwe tools,
rollenlijst in de executor of scheduler. Het jobpakket bevat het frozen algemene
rolcontract, concrete missie en outputcontract. Recovery hergebruikt dezelfde
missie/assignment en maakt uitsluitend een nieuwe attempt na operatorbewijs.
Losse claims omzeilen deze binding niet; recovery naar succeeded zonder atomair
gevalideerde output wordt geweigerd.

Kuifje zoekt binnen de opdracht, maximaal 20 inhoudelijk gereviewde bronnen en
5 fiches per missie (de backend handhaaft de fichegrens). Hij maakt geen nieuwe
missies/dossiers en wijzigt geen Leonardo-geheugen. Hij krijgt geen algemene
recallbevoegdheid; vraag, aanleiding en scope moeten zelfstandig bruikbaar zijn.
Succes schrijft apart kuifje_result={summary,limitations} en de geleverde
result_ref, ook bij lege oogst. Failed/uncertain heeft geen outputrefs/resultaat;
de generieke error/attemptaudit bewaart de fout. Reeds gepubliceerde fiches blijven
behouden bij een latere failure, met hun oorspronkelijke producerende attempt.

## Bestaande ficheketen

Kuifje gebruikt dezelfde submit_weekendkrant_fiche en POST /ingress met de
ongewijzigde vier inhoudsvelden schema_version/date/topic/content. mission_id,
fiche_id en claim zijn transportmetadata; run_id is exclusief voor Sherlock.
De ingress stript deze metadata en bewaart de producerbinding apart in
kuifje_fiches: queue-item, Kuifje-job, producerende attempt, stabiele fiche_id en
payloadhash. Mission → assignment → job levert de dossierbinding.

Actuele lease, token, meest recente attempt, executorbinding en missietopic
worden onder de ingresslock gecontroleerd, ook bij retries. De klok wordt na
lockverwerving gelezen. Dezelfde job/fiche_id/payload retourneert dezelfde
queue-ID; een gewijzigde payload conflicteert. Een herstelde attempt kan dezelfde
fiche bevestigen zonder de oorspronkelijke producer te overschrijven. Na
claimverlies mag ook een retry niets meer publiceren.

Ariadne materialiseert deze gewone fiches via source_archive/revision_sources
naar nieuwe immutable partrevisions. De keten is terug te volgen met
revision_sources → kuifje_fiches → kuifje_assignments → kuifje_missions.
Een latere gewone Leonardo-enqueue krijgt expliciet geselecteerde nieuwe
revisies voor het bestaande dossier; fase 12 introduceert geen automatische
inhoudelijke dossierrouter of offerselectie. Kuifje schrijft nooit rechtstreeks
in parts of Leonardo-state.

## Eén meetinstrument van Ariadne

ariadne_tokens.py bevat de canonieke cl100k_base-primitive. daily,
part_format_v1 (historische reconstructie), Leonardo en Kuifje gebruiken haar;
de dubbele encode-implementatie is verwijderd zonder wijziging van de
historische tokenberekening. Dit is Ariadne's gedeelde lokale meetlat, geen
agent-eigen tokenizer en geen providerusage, verborgen modeltokens of geldkost.

Reevaluation bewaart tokens in het bestaande assignment en tokenizer-identiteit
in de frozen snapshot; UTF-8 bytes zijn exact uit die immutable tekst afleidbaar.
Missie en Kuifje-assignment bewaren bytes/tokens/tokenizer expliciet; ook het
terminale Kuifje-resultaat wordt zo gemeten. Inspectie blijft compact en lokaal.
De canonieke auditidentiteit is cl100k_base volgens het bestaande partcontract;
een wijziging ervan vereist een expliciet nieuw versiecontract.

## Operatorpad en invoering

Na code-update: voer de centrale database.py-migratie naar schema 13 uit en
herstart de ingressbackend. Synchroniseer/publiceer daarna de Sites-brug met de
nieuwe optionele finish- en fichevelden voordat nieuwe jobs worden uitgevoerd.
Deze PR voert die operationele handelingen niet uit.

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
```

De Leonardo-inspectie toont dossier, basisversie, mode, new_part_count=0,
previous_state_tokens, recallaudit per attempt, outputstate-tokens en
mission_count. Missie-inspectie toont identiteit, producerende Leonardo-job,
dossier/stateversie, provenance, bytes/tokens/tokenizer, gekoppelde Kuifje-job,
status, assignmentomvang en ficheaantal. Status leeft op de generieke job,
nooit als mutable tekst in de missie.

## Gerichte validatie

De fast-track bevat uitsluitend test_phase12 en drie bestaande grensregressies:
de gewone Leonardo-statecyclus, gemengde part-/queueprovenance en frozen
historische reconstructie bij een gewijzigde actieve tokenizer. De nieuwe
integratietests dekken ook HTTP, foutrollback, immutable opslag, frozen context,
zero-input recall, terminale retries, fencing/recovery, additive migratie,
canonieke tokenaudit en de lokale ingress → Ariadne → volgende Leonardo-inputlus.
De pluginlaag heeft een eigen transporttest en echte MCP → HTTP → SQLite →
Ariadne-test met verloren antwoorden na missie-, fiche- en finishcommit.
Validatie gebruikt uitsluitend ./start_tests.sh en ./start_tests.sh --plugin.
De volledige regressiesuite blijft aan de afzonderlijke CI op de exacte commit.

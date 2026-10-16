# Fase 9: expliciete operatorproef, eerste slice

De lokale `leonardo_operator.py` maakt gecontroleerde offer → dossier → job-routing
uitvoerbaar. De bestaande dispatcher, scheduled executor en fase-8-statefinish
blijven de enige uitvoeringsroute. Geen nieuwe scheduler, publieke MCP-tool,
model-API-call vanuit bibib of permanente Leonardo-worker. Ariadne kiest geen
semantisch dossier. Topic is geen dossier, meerdere dossiers per topic blijven
mogelijk. Er is geen automatische offerconsumptie of vaste topicvolgorde.

De menselijke/operator-dossierkeuze is uitsluitend teststeun voor deze eerste
gecontroleerde cyclus, niet het doelmodel van Weekendkrant. Het uiteindelijke
systeem moet zichzelf zonder menselijke routing organiseren. Toekomstige
semantische dossierkeuze vereist intelligentie; welke rol of policy dat precies
doet blijft open. Eén dossier per topic, topic-ID → dossier-ID, first-offer-wins,
een vaste topicvolgorde of semantische interpretatie door Ariadne zijn daarvoor
geen vervanging. Ariadne blijft de deterministische opslag-, validatie-, budget-
en routinglaag. Deze PR implementeert die automatische keuze niet.

Leonardo voert tijdens de proef zijn actuele [runtimecontract](../roles/leonardo.md)
uit: structurele/semantische organisatie van aangeboden materiaal. Eerdere state
is compacte context; rolling state en `previous_version` geven continuïteit en
geen opdracht tot longitudinale trendanalyse. Temporele bronfeiten mag hij wel
gebruiken. Analyse van evolutie doorheen states hoort later bij Einstein, die
hier geen runtime krijgt.

Deze oorspronkelijke PR leverde een reproduceerbaar lokaal bewijs van
operatorbrug → dispatcher → statefinish. De eerste **echte** Sherlock → Ariadne →
offer → scheduled Leonardo → state-cyclus is op 16 oktober 2026 daarna
operationeel uitgevoerd en vastgelegd.

## Resultaat van de eerste productieproef

De eerste Leonardo-job schreef succesvol dossierstate v1. Een eerdere attempt
expireerde; attempt 2 voltooide via de bestaande generieke executor en fenced
finish. De immutable assignment mat lokaal 23.665 `cl100k_base`-inputtokens en
de opgeslagen state 1.844 tokens. De state bevatte 6 hypotheses, 13 claims,
6 onzekerheden en 6 open vragen voor één verwerkte partrevisie. Deze aantallen en
tokenmetingen zijn karakteriseringsdata, geen inhoudelijke kwaliteitsscore en
evenmin providerusage of productkost.

De belangrijkste architecturale bevinding is dat rolling state bruikbaar is als
compacte structurele kenniskaart, maar bewust verliesgevend moet kunnen blijven.
De bronlaag bewaart de oudere informatie lossless; de huidige Leonardo-job kan
eerder verwerkte refs echter nog niet tijdens een latere iteratie opnieuw
opvragen. Zonder zo'n historical-recallbrug zou opeenvolgende compressie een
oud detail uit de actieve context kunnen laten verdwijnen terwijl de bron zelf
nog wel veilig opgeslagen is.

Daarom volgt vóór fase 10 eerst fase 9.6: selectieve read-only historical recall,
recalltelemetrie en Leonardo-karakterisering met een verruimde technische
contextgrens. Kuifje blijft buiten deze stap. Pas nadat Leonardo betrouwbaar kan
vergeten én terugvinden, krijgt hij later een actiepad om een concrete lacune als
persistente Kuifje-missie via Ariadne/backend te laten ontstaan.

## Voorwaarden en stopgrenzen

Deze PR deployt niets en voert de productieproef niet uit. De operator heeft na
fase 8.5 bevestigd: schema 11 is gedeployd, bibib draait fase-8.5-code, de
gepubliceerde Sites-bridge exposeert `leonardo_state` en de scheduled executor is
gesynchroniseerd met de rolagnostische `executor/instructions.md`. Sherlock- en
Leonardo-runtimecontracten leven onder `roles/`. Dit is de aangeleverde actuele
deploymenttoestand, geen nieuwe productiemeting door deze PR.

Na merge moet de operatorcode afzonderlijk naar bibib worden gedeployd. Controleer
vóór de echte proef opnieuw de actuele runtime:

1. Controleer checkout/backendversie, `PRAGMA user_version` (11), actieve
   executorinstructie en de gepubliceerde `tools/list` met
   `finish_weekendkrant_job.inputSchema.properties.leonardo_state`. Bewaar
   versie en controletijd. Stop bij drift tot die afzonderlijk is opgelost.
2. Lees running/blocked jobs, dispatcher pause/concurrency en backlog. Bijvoorbeeld
   met uitsluitend lezende SQL, zonder claims of expirysweep:

   ```bash
   sqlite3 -readonly /home/weekendkrant/weekendkrant.sqlite3 'SELECT * FROM dispatcher_policy;'
   sqlite3 -readonly /home/weekendkrant/weekendkrant.sqlite3 "SELECT id,role,status,created_at FROM jobs WHERE status IN ('ready','running','blocked') ORDER BY id;"
   ```

   Wijzig geen lifecycle met SQL. Gebruik voor herstel het bestaande
   [operatorrecoverycontract](jobs.md), nooit alleen een verstreken lease.
3. Controleer beschikbare offers en dossiers met de CLI hieronder. Herleid gekozen
   offers via bronprovenance tot de Sherlock-oogst en Ariadne-materialisatie.
   Ontbreekt passende sealed input, wacht op de bestaande keten; forceer geen
   offer of dossierkeuze om de proef te laten slagen.

Nieuwe jobs lopen uitsluitend via `LeonardoStore.enqueue()`: die leest de actuele
`roles/leonardo.md` en `roles/leonardo-output.md` en bevriest beide contracten in
de immutable assignment. De operator leest of injecteert geen prompttekst.
Dispatcher `bind()` levert die snapshot; bestaande jobs, retries en uitvoering
lezen geen actuele `roles/*.md`. Wijzig de generieke executor niet voor Leonardo.

## Bewuste selectie en enqueue

Onderstaande opdrachten draaien lokaal als bevoegde operator op bibib vanuit de
checkout met zijn bestaande Pythonomgeving. Vervang dossier, offer-ID's, baseversie
en operatie-ID door bewust gekozen waarden. Het dossier-ID benoemt een
inhoudelijk dossier, geen automatisch topicbakje. Stel de shellvariabelen hieronder
bewust in met gekozen waarden; `JOB_ID` komt uit het enqueueantwoord. Herhaal
`--offer` voor meerdere gekozen offers (maximaal 32), in de gewenste volgorde.

```bash
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 offers
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 dossiers
# Alleen als bewust een nieuw dossier nodig is:
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 create-dossier --dossier "$DOSSIER" --topic "$TOPIC"
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 enqueue --dossier "$DOSSIER" --base-version "$BASE_VERSION" --operation-id "$OPERATION_ID" --offer "$OFFER_ID"
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 inspect --job "$JOB_ID"
```

Gebruik uitsluitend ID's uit `offers`, met het juiste topic. De brug accepteert
geen part/revisionargument: zij resolveert uitsluitend immutable `part_offers`
en controleert dat het part sealed is. Ze gebruikt exact de aangeboden revisie,
nooit de actuele revisie als vervanging. Onbekende offers, duplicaten, verkeerde
topics, verouderde baseversies en onafgerond dossierwerk worden geweigerd via de
brug en bestaande fase-8-validatie. De bestaande snapshots en inputlimieten gelden.
De CLI maakt geen offers en kiest geen bronnen of dossiers.

Noteer vóór enqueue de actuele baseversie uit `dossiers` en controleer de inhoud
van de gekozen revisies via bestaande provenance/reconstructie. Enqueue controleert
de baseversie opnieuw onder de bestaande korte schrijflock. Een race weigert de
opdracht; kies niet automatisch een nieuwe basis. Dossiercreatie is een aparte,
idempotente expliciete stap en kan blijven bestaan na een geweigerde enqueue.

Bewaar de volledige enqueueopdracht. Bij onzeker antwoord: **dezelfde operation-ID
en exact dezelfde dossier/baseversie/geordende offerlijst** herhalen, ook als de
state inmiddels vooruitgegaan is. Gewijzigde opdracht vereist onderzoek en een
nieuwe identiteit. De bestaande assignmentreceipt retourneert dezelfde job.
Een offer is niet wereldwijd verbruikt: hergebruik wordt niet automatisch gekozen
of verboden. Dit experiment definieert geen consumptiepolicy.

## Tijdens en na de geplande uitvoering

Start geen tweede executor voor deze proef. Laat de bestaande scheduled executor
het ready werk oppakken. `inspect --job` geeft een consistent JSON-leessnapshot,
zonder claimtoken of nieuwe rapporttabellen:

- gekozen offer-ID, exacte part/revision en offertimestamp;
- dossier, immutable baseversie, operation-ID, jobstatus en creatie/update/eindtijd;
- queue-ID, Sherlock-run-ID (null betekent onbekend), materialisatietijd per bron;
- attempts met activation-ID, status, start, lease-einde en eindtijd;
- persistente dispatcherselectie met activation/attempt en bevestigingstijd;
- ready/running/blocked backlog per rol, aantallen en oudste creatietijd;
- inputtokens en UTF-8-bytes van het gehele immutable assignmentsnapshot;
- bij succes: exacte state, versie, predecessor, attempt, timestamp, tokens en bytes;
- objectieve toegevoegde/verwijderde/gewijzigde item-ID's per statecategorie en
  nieuwe `processed_refs`, vergeleken met de assignmentbasis.

Bewaar het rapport vóór dispatch, tijdens uitvoering en na finish buiten stdout
indien nodig. Verschillen tussen offer.created_at, job.created_at,
attempt.started_at en state.created_at tonen aanbiedwachttijd, ready-wachttijd
en uitvoeringsduur. Backlog bevat de huidige telling en oudste tijd, geen
historische reconstructie of modelusage. Een inspectie valideert of verlengt geen
lease en voert geen expirysweep uit. Een lege dispatcherselectie vóór dispatch is
normaal; bij uitblijven inspecteer pause/concurrency en andere ready jobs volgens
[het dispatchercontract](dispatcher.md). Een failed/blocked job is geen succes.

Controleer bij succes dat versie = base + 1, predecessor = base (SQL NULL bij
basis 0), job/attempt succeeded zijn en `processed_refs` exact de vorige refs plus
de aangeboden refs bevatten. Inspecteer inhoudelijk de nieuwe/veranderde
hypotheses, claims, onzekerheden en vragen met hun bronondersteuning. Itemwijziging
of tokenaantal is geen bewezen informatiewinst. Er bestaat geen verzonnen score.
Leg gebruikte IDs, tijden, rapporten, inhoudelijke bevindingen en beperkingen vast
als proefbewijs. De eerste inhoudelijke beoordeling is inmiddels uitgevoerd en leidde nog niet tot
een automatische offer-to-jobpolicy. Eerst wordt de historical-recallgrens
geïmplementeerd en over meerdere Leonardo-iteraties gekarakteriseerd. Kuifje,
missies, Striktland, Minos en eindredactie blijven buiten deze oorspronkelijke
proefslice.

## Fase-9.6-vervolg: historical recall karakteriseren

De lokale implementatie gebruikt schema 12 en de nieuwe tool
`recall_weekendkrant_part`. Productie-invoering en nieuwe scheduled proeven zijn
nog niet uitgevoerd. Vóór een vervolgproef moeten backend/schema en de gepubliceerde
MCP-brug gesynchroniseerd zijn. Nieuwe jobs bevriezen het bijgewerkte rolcontract;
bestaande jobs blijven hun oude immutable tekst uitvoeren. Er is geen nieuwe
scheduler of gewijzigde executorinstructie nodig.

Gebruik na een vervolgjob de compacte lokale audit:

```bash
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 inspect --job "$JOB_ID" --compact
```

`context_usage.attempts` bewaart ook failed/expired attempts. Vergelijk
`new_part_count`, `new_part_tokens`, `new_part_bytes` en de `new_parts`-lijst
(ref/tokens/bytes in assignmentvolgorde), `previous_state_tokens`, totale
startinputtokens, recalls op volgorde, tokens/bytes per recall, cumulatieve
recallcontext en uiteindelijke state-tokens afzonderlijk. `provider_usage:null`
betekent onbekend. Herhaalde transportantwoorden en reasoning/cachegebruik
worden niet gemeten door deze lokale tellingen. Geen fictieve nulprijs of
providerrekening afleiden uit lokale `cl100k_base`-aantallen.

De oorspronkelijke 35K was een arbitraire eerste cognitieve chunkinghypothese,
geen kostenlimiet: voorkom dat te veel onbekend nieuw materiaal tegelijk het
overzicht aantast. Deze hypothese laten we nu bewust los; ook de nieuwe technische
noodrem claimt geen optimale behapbare brok. Beoordeel specifiek de hoeveelheid
nieuw aangeboden bronmateriaal tegenover de kwaliteit van de structurele synthese.

Beoordeel over meerdere iteraties of Leonardo nieuwe informatie in bestaande
structuur integreert en oude details gericht kan terughalen. Die inhoudelijke
karakterisering is nog open. Kuifje en missievoorstellen blijven fase 10.

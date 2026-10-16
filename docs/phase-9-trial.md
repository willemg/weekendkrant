# Fase 9: expliciete operatorproef, eerste slice

De lokale `leonardo_operator.py` maakt gecontroleerde offer → dossier → job-routing
uitvoerbaar. De bestaande dispatcher, scheduled executor en fase-8-statefinish
blijven de enige uitvoeringsroute. Geen nieuwe scheduler, publieke MCP-tool,
model-API-call vanuit bibib of permanente Leonardo-worker. Ariadne kiest geen
semantisch dossier. Topic is geen dossier, meerdere dossiers per topic blijven
mogelijk. Er is geen automatische offerconsumptie of vaste topicvolgorde.

Deze PR levert een reproduceerbaar lokaal bewijs van operatorbrug → dispatcher
→ statefinish. De eerste **echte** Sherlock → Ariadne → offer → scheduled
Leonardo → state-cyclus moet daarna operationeel worden uitgevoerd en vastgelegd;
lokale tests bewijzen geen modeluitvoering of productiepublicatie.

## Voorwaarden en stopgrenzen

Voer geen productiedeployment uit als onderdeel van deze PR. Vóór de echte proef:

1. Controleer schema 11/backendversie en de actieve executorinstructie tegen
   `docs/agents/executor.md`.
2. Bewaar bewijs van `tools/list` op de **gepubliceerde** Sites `/mcp`:
   `finish_weekendkrant_job.inputSchema.properties.leonardo_state` moet aanwezig
   zijn en overeenkomen met het fase-8-schema in
   `plugin/weekendkrant_ingress/worker/index.js`. Noteer URL, controle-UTC-tijd en
   gepubliceerde versie. Alleen repo-code of een lokale test is geen bewijs.
   Ontbreekt de parameter, stop de proef tot de bridge aantoonbaar bijgewerkt is.
3. Controleer bestaande running/blocked jobs en dispatcherpause/concurrency.
   Wijzig geen lifecycle met SQL. Gebruik voor herstel het bestaande
   [operatorrecoverycontract](jobs.md), nooit alleen een verstreken lease.

## Bewuste selectie en enqueue

Onderstaande opdrachten draaien lokaal als bevoegde operator op bibib vanuit de
checkout met zijn bestaande Pythonomgeving. Vervang dossier, offer-ID's, baseversie
en operatie-ID door bewust gekozen waarden. Het dossier-ID benoemt een
inhoudelijk dossier, geen automatisch topicbakje.

```bash
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 offers
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 dossiers
# Alleen als bewust een nieuw dossier nodig is:
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 create-dossier --dossier proef-replicatie --topic 2
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 enqueue --dossier proef-replicatie --base-version 0 --operation-id fase9:replicatie:001 --offer 17 --offer 18
python leonardo_operator.py --db /home/weekendkrant/weekendkrant.sqlite3 inspect --job 42
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
als proefbewijs. Pas daarna beslissen we welke automatische offer-to-jobpolicy
zinvol is. Kuifje, missies, Striktland, Minos en eindredactie vallen buiten deze slice.

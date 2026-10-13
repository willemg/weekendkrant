# Intelligente workers, rollen en persistente redactie

## Status en ontwerpbesluit van 13 oktober 2026

Dit document is het canonieke doelontwerp voor execution identity en orchestratie
van Weekendkrant. Het generaliseert het
[Leonardo-geheugenontwerp van 8 oktober](leonardo-memory-and-orchestration.md):
een vervolguitvoering werkt met expliciet terug aangeboden state en bronnen,
zonder een langlevend modelproces nodig te hebben.

| Status | Wat bestaat of is besloten |
| --- | --- |
| Huidige geïmplementeerde runtime | Sherlock-specifieke runstart met atomaire topicrotatie, bronfiltering en source-audit; fiche-ingress naar SQLite; deterministische `daily`-materialisatie naar week/topic-parts met immutable revisies, bronarchief en lokale offer/seal-records. |
| Huidig beschreven operationeel ritme | Sherlock behandelt volgens zijn canonieke instructies één toegewezen topic per uurrun. Ariadne draait volgens het lokale croncontract dagelijks om 10:00 in `Europe/Brussels`. Repository-instructies bewijzen op zichzelf geen actieve schedulerconfiguratie of deployment. |
| Gekozen doelrichting | Generieke scheduled executors krijgen per activatie maximaal één begrensde job met een door de backend gekozen rol. Persistente state draagt de redactionele continuïteit. Lokale Ariadne-materialisatie moet minstens uurlijk, mogelijk sneller, kunnen draaien. |
| Nog niet geïmplementeerd | Generieke jobqueue, attempts/claims, dispatcher, generieke MCP-control-plane, Leonardo-state en -jobs, dossiers, missies, drafts, verificatie- en correctiejobs, capaciteitsbeleid en automatische eindredactie. |

Deze documentatiestap verandert geen runtimecode, schema, plugin, actieve
taakinstructies, cron, systemd of deployment. De bestaande runtimecontracten
blijven geldig. Bij een verschil tussen oude doelontwerpen en dit document is
dit document leidend voor de nieuwe orchestratie; het vervangt geen beschrijving
van reeds geïmplementeerd gedrag.

## Centraal principe

> Sherlock, Leonardo, Kuifje, Striktland en Minos zijn rollen, geen fysieke
> workers. Een scheduled worker is een generieke intelligente executor die per
> activatie precies één begrensde job uitvoert wanneer werk beschikbaar is.
> Identiteit en continuïteit zitten in persistente Weekendkrant-state.

`role != worker` en `job != model personality`.

Een worker kiest zijn rol niet zelf. De backend levert een concrete opdracht,
bijbehorend rolcontract en begrensde context. Een activatie zonder nuttig werk
stopt zonder intelligente job. Een worker start of spawnt nooit een volgende
worker, en claimt na afronding geen tweede job binnen dezelfde activatie.

## Begrippen

| Begrip | Betekenis in het doelontwerp |
| --- | --- |
| Scheduled executor / worker | Generieke intelligente uitvoerder die bij een scheduled activatie één opdracht kan uitvoeren; heeft geen permanente redactionele rol of betrouwbaar eigen geheugen. |
| Role | Inhoudelijk contract voor Sherlock, Leonardo, Kuifje, Striktland of Minos. Bepaalt verantwoordelijkheden, toegestane acties en vereiste output. |
| Job | Eén begrensde opdracht met stabiele `job_id`, rol, inputreferenties, uitvoeringsvoorwaarden en outputcontract. |
| Job attempt | Eén geregistreerde uitvoeringspoging van dezelfde job, met eigen identiteit, claim, tijden en uitkomst. Een retry van uitvoering hoeft geen nieuwe job te worden. Een losse toolretry is niet automatisch een nieuwe attempt; de exacte grens volgt later. |
| Dispatcher | Deterministische backendlogica die op expliciete work/state en configureerbare regels beslist welke uitvoerbare job beschikbaar komt. |
| Persistent state/artifact | Opgeslagen bronmateriaal, concrete partrevisie, dossierstateversie, missie, draft, resultaat of audit met stabiele referenties; onafhankelijk van workergeheugen. |
| Dossier | Langlevend inhoudelijk onderzoek met eigen identiteit, state, hypotheses, claims, bronverwijzingen en eventuele missies. Een topic of fysieke part is niet automatisch een dossier. |
| Missie | Expliciete, begrensde onderzoeksvraag met `mission_id`, dossierkoppeling, context, status en resultaat; kan een Kuifje-job voeden. |

De huidige `sherlock_runs` zijn Sherlock-specifieke audit, geen generieke jobs.
De bestaande tabel `attempts` registreert Ariadne-runtimefouten en is evenmin
het toekomstige intelligente job-attemptmodel.

## Protocol en invarianten

Het conceptuele protocol, zonder nu toolnamen of schemas vast te leggen:

1. Een scheduled activatie vraagt de backend om werk en claimt atomair een job.
2. Is er geen uitvoerbaar nuttig werk, dan stopt de activatie.
3. Anders ontvangt de executor `job_id`, attempt-/claimidentiteit, rolcontract
   en begrensde input/context met concrete artifactreferenties.
4. Hij voert exact die job uit en registreert resultaten en state expliciet.
5. Hij sluit de jobpoging af volgens het resultaat-/foutcontract en stopt.
6. Een latere scheduled activatie kan een volgende job uitvoeren.

Daarbij gelden de volgende doelinvarianten:

- Eén scheduled activatie voert maximaal één intelligente job uit.
- Iedere job heeft een stabiele identiteit; uitvoeringspogingen blijven apart
  traceerbaar. De backend kiest de rol en de opdracht.
- Workers spawnen geen workers en geven andere executors niet rechtstreeks werk.
  Een inhoudelijk missievoorstel wordt opgeslagen en door de backend gevalideerd.
- Continuïteit zit in persistente state en expliciet meegegeven bronnen.
  Een modelsamenvatting wordt nooit vanzelf een primaire bron.
- Input, output, duur en toegestane acties zijn begrensd. Concrete grenzen en
  herstelovergangen moeten nog worden gekozen.
- Resultaten worden gekoppeld aan job, attempt en gebruikte inputversies.
  Een onbevestigde finish geldt niet als bevestigde succesvolle uitvoering.
- Gelijktijdige executors mogen dezelfde job niet dubbel uitvoeren. Claims en
  resultaatacceptatie moeten dit bewaken, ook bij crashes en verlopen claims.
  Een lock alleen bewijst geen exactly-once uitvoering van externe side effects.
- Intelligente concurrency blijft expliciet begrensd. Opschalen van één naar
  meerdere schedulers verandert het jobprotocol niet.
- Langdurige intelligente uitvoering houdt geen SQLite-write-transactie open.
- Retries respecteren de bevestigde effecten en idempotentie van de operatie;
  een onzekere fichepublicatie wordt niet blind herhaald.

## Dispatcher: reageren op werk en state

De dispatcher moet uiteindelijk reageren op aanwezige work/state. Een vaste
`S,S,S,L,...`-reeks zou ook Leonardo starten zonder nieuwe input, of een open
missie laten wachten terwijl nuttig werk beschikbaar is.

| Expliciet beschikbare conditie | Mogelijke job |
| --- | --- |
| Recente topicdekking voldoet niet aan vastgelegde meetbare voorwaarden | Sherlock voor dat topic |
| Voldoende nieuwe beschikbare partrevisies en geldige dossierstate volgens gekozen aanbiedregels | Leonardo |
| Open, gevalideerde onderzoeksmissie met context en budget | Kuifje |
| Draft/claims met concrete bronreferenties klaar voor controle | Striktland |
| Striktland registreert een relevant probleem volgens het afgesproken resultaatcontract | Minos |
| Geen nuttig uitvoerbaar werk, onvoldoende budget of pause actief | Geen intelligente job |

Dit zijn ontwerpvoorbeelden, geen reeds geïmplementeerde selectievoorwaarden.
Grenzen voor recentheid, hoeveelheid input, prioriteiten en relevant-probleemlabels
moeten expliciet worden vastgelegd. Ariadne past die regels mechanisch toe.
Zij bedenkt geen onderzoeksvragen en interpreteert geen inhoudelijke relevantie.
Leonardo kan bijvoorbeeld een dossierverband of missie formuleren; Ariadne
valideert identifiers, contract en budget en maakt de toegestane job beschikbaar.

Begin met één scheduler, topicrotatie en harde limieten. Voeg pas schedulers toe
als een aantoonbare backlog van nuttig intelligent werk dat rechtvaardigt.
Niet-uitvoerbaar werk en lege slots veroorzaken geen vervangende bezigheid.

## Ariadne: lokale deterministische verwerking

Ariadne blijft lokale deterministische software. Zij mag niet samenvatten,
relevantie beoordelen, semantisch dedupliceren, patronen herkennen of inhoudelijke
onderzoeksvragen bedenken. Zij mag persistente state beheren, input en output
koppelen, jobs beschikbaar maken en atomair claimen, workflowvoorwaarden en
harde budgetten controleren, dubbele claims voorkomen en resultaten mechanisch
naar expliciete dossiers, missies en jobs terugrouteren. Deze uitbreiding van
haar regietaak is doelontwerp, geen huidige jobruntime.

De huidige `daily`-verwerking eenmaal per dag om 10:00 is te traag voor deze
redactie. Als drie Sherlock-rondes nieuwe fiches leveren en daarna Leonardo
aan de slag moet, moet die oogst tijdig in lokale part/revision-state staan.

De gekozen doelrichting is **minstens eenmaal per uur materialiseren, mogelijk
duidelijk vaker**. De exacte cadence blijft open en wordt empirisch gekozen op
basis van ingest, materialisatieduur en gewenste inputversheid. Een lokale
systemd timer of vergelijkbare scheduler ligt voor de hand; deterministisch werk
verbruikt geen intelligent scheduled slot. Deze PR installeert geen timer.

Behoud het bestaande snapshot-, provenance-, runtime-slot- en partprotocol met
korte transacties. Maak onderscheid tussen vaker materialiseren en een part
aanbieden/sealen voor intelligent gebruik: niet iedere materialisatie hoeft een
offer of Leonardo-job te veroorzaken. `PartStore.offer` bestaat al lokaal;
het automatische aanbiedmoment en daadwerkelijke modelontvangst bestaan nog niet.

## Capaciteit, context en budget

Scheduled activaties zijn schaarse intelligente uitvoeringsslots. Het huidige
operationele denkmodel is maximaal vijf scheduled workers die elk hoogstens
ongeveer eenmaal per uur worden geactiveerd, conceptueel dus maximaal
`5 × 24 = 120` intelligente jobstarts per dag. Dit is een planningsaanname,
geen geverifieerde blijvende platformgarantie of domeininvariant. Leg `5` en
`120` niet vast als schema-invariant. Werkelijk bruikbare capaciteit kan lager
zijn door productlimieten, allowance, fouten en gebrek aan nuttig werk.

De experimentele Sherlock-observaties die aanleiding geven tot dit besluit zijn
ongeveer 24–38 inhoudelijk gereviewde bronnen per run, meestal 30–35, met een
typische looptijd van 4–10 minuten: grofweg 10% van een uur. Deze cijfers komen
uit de aangeleverde projectobservaties; deze documentatie-audit heeft de live
runhistoriek niet opnieuw gemeten. Het zijn geen SLA of vaste uitvoeringsgrenzen.

De vrije ruimte is aanleiding om andere redactionele rollen nuttig in te zetten,
niet om dezelfde brede Sherlock-zoeklus automatisch tienmaal langer te maken.
Een korte job geeft binnen dezelfde activatie geen recht op een tweede job;
ander werk volgt in een latere beschikbare activatie.

| Budget | Betekenis en beleid |
| --- | --- |
| Context/tokenbudget per job | Begrensde volledige input en afzonderlijke outputgrens. De bestaande 35K-inputgrens blijft relevant als context-/kwaliteitsgrens voor Leonardo; 30K bronpart plus 5K overige input is geen garantie dat iedere samengestelde request past. Meet het geheel volgens het gekozen uitvoeringscontract. |
| Intelligente jobstarts | Configureerbaar aantal beschikbare activaties; alleen gebruiken voor nuttig werk. Een retry/attempt en verloren activatie moeten zichtbaar meetellen volgens later gekozen beleid. |
| Gedeelde productallowance | Weekendkrant deelt beschikbare productcapaciteit met handmatige/persoonlijke intelligente arbeid. Concrete reservering, prioriteit en terugschakeling blijven open. |
| Lokale deterministische verwerking | Verbruikt geen intelligent slot; de marginale lokale rekenkost is verwaarloosbaar, maar hosttijd en opslag blijven meetbaar. |

API-dollarbudget is niet langer het centrale architecturale uitgangspunt.
Oude API-kostenreserveringen en modelvoorkeuren zijn eerder doelontwerp, geen
bewijs dat zulke betaalde calls nu draaien. Als later een betaalde uitvoeringsroute
wordt gekozen, krijgt die een expliciet eigen kostencontract. Minder herlezen,
compacte rolling state, traceerbaarheid en harde contextgrenzen blijven waardevol.
Beschikbare slots hoeven nooit automatisch allemaal verbruikt te worden.

## Behouden fundamenten

Behoud persistente ingressqueue en SQLite, exact bronarchief, immutable
partrevisies, bronmembership/provenance, deterministisch weaving, tokenmetingen,
crashsafe korte transacties, source-level Sherlock-audit en de inhoudelijke
rolscheiding. Verander vooral orchestratie en execution identity.

Striktland krijgt alleen relevant bewijs bij concrete claims. Minos krijgt alleen
problematische passages met noodzakelijk bewijs en wordt alleen bij een werkelijk
relevant probleem ingeschakeld. Na de standaard Minos-correctie volgt geen nieuwe
automatische verificatieregressie. Kwaliteitslabels en oorspronkelijke bronnen
blijven traceerbaar. Dossierstate blijft verliesgevende compressie met expliciete
onzekerheden en toegang tot origineel materiaal.

## Documentatie-audit en latere aanpassingen

Audit uitgevoerd op `main`-commit
`0c0320e92acd34c2d9948506c069fd8c663abd18`. De onderstaande verschillen zijn
migratiewerk; bestaande runtimebeschrijvingen worden niet vooruitlopend herschreven.

| Gecontroleerd document | Bevinding en latere aanpassing |
| --- | --- |
| [README](../README.md) | Beschrijft huidige queue/parts correct en bevat dagelijkse cron. De introductie en principes verwijzen nog naar dure modelcalls; later de bewezen generieke jobruntime en capaciteit opnemen. Nu alleen een link/statusnotitie toevoegen. |
| [Architectuur](architecture.md) | Huidige lokale storage, korte transacties, discovery en dagelijks 10:00-contract behouden. Na implementatie job/control-plane, dispatcher en nieuwe cadence toevoegen. |
| [Rollen](roles.md) | Sherlock wordt als actieve taak en dagelijkse voorganger van Ariadne beschreven; dat loopt achter op één topic per uurrun in de canonieke instructies. Ook vijf actieve nieuwstaken, cross-domain triage en nog te kiezen ficheformaat zijn oudere beschrijvingen. Later rol versus executor expliciet maken en bewezen rolcontracten synchroniseren. |
| [Leonardo-geheugen en regie](leonardo-memory-and-orchestration.md) | Continuïteit via state/bronnen, dossiers, missies en lokale offers hergebruiken voor alle rollen. Kostenadministratie, callbouwer en modelidentiteit zijn ouder doelontwerp; later aan jobs/attempts en scheduled uitvoering aanpassen. |
| [Token- en kostenstrategie](token-and-cost-strategy.md) | Leonardo als voornaamste betaalde laag en modelvoorkeuren zijn oud API-doelontwerp. Later activaties, allowance en contextgrenzen scheiden; bestaande bundelmetingen behouden. |
| [Dagelijkse runtime](daily-runtime.md) | Snapshot, lokale lock, korte eindtransactie, immutable files en offer/seal behouden. Later frequente lokale materialisatie en operationele cadence documenteren; dagelijks croncontract blijft nu actueel beschreven gedrag. |
| [Database](database.md) | Versie 4 heeft Sherlock-runs/sources, geen generieke jobs of leases. `attempts` is lokale runtimefoutaudit. Later nieuwe additieve migratie en generieke claims, state- en outputkoppelingen documenteren. |
| [Audit trail](audit-trail.md) | Bron-/revisieprovenance bestaat; claim-, dossier- en callaudit zijn gepland. Later job/attempt-identiteit, daadwerkelijke inputs/resultaten en ficheproducent toevoegen. |
| [Ingress-runtime](ingress-runtime.md) | Vier Sherlock-state endpoints en fiche-ingress bestaan; atomaire topicrotatie is geen generieke claim. De uitspraak over iedere herhaalde POST die een nieuw item maakt betreft `/ingress`, niet filter/finish/bronregistratie. Later generieke control-plane en retrycontracten per operatie verduidelijken. |
| [Redactionele principes](editorial-principles.md) | Bronvastheid, scheiding feit/inferentie, klein beginnen en eindige controle blijven geldig; later jobartefacten aan menselijke inspectie koppelen. |
| [Canonieke Sherlock-instructies](agents/sherlock.md) | Eén topic per uurrun, backendrotatie, source-audit, fichepublicatie, batching en experimentele safety-retries behouden. Later bootstrap naar generieke claim/rolcontract migreren; deze PR verandert de actieve instructies niet. |
| [Plugin-README](../plugin/weekendkrant_ingress/README.md) | Vijf bestaande tools en afzonderlijke GitHub→Sites-sync/publicatie behouden. Later generieke tools, concurrency en outputkoppeling beschrijven; broncode is geen deploymentbewijs. |

De code-audit van `ingress_api.py` bevestigt bovendien compacte requestlogging
met toolnaam, fase, HTTP-status en waar beschikbaar `run_id`. Dat vult source-audit
aan, maar koppelt fiche-output nog niet canoniek aan de producerende run/job.

## Gefaseerde, afvinkbare migratie

De volgorde hieronder is de beoogde afhankelijkheidsvolgorde. Een fase wordt pas
afgevinkt wanneer haar resultaat aantoonbaar bestaat; een ontwerpcheckbox bewijst
geen deployment. Fase 1 is gerealiseerd door de documentatiestap; fase 2 wordt
hieronder per gerealiseerde meting bijgehouden. Iedere runtimefase krijgt afzonderlijke implementatie,
validatie en operationele invoering.

### Fase 1 — architectuur canoniek maken

- [x] Generieke worker/job/role-architectuur vastleggen.
- [x] Huidige runtime, gekozen doelrichting en niet-geïmplementeerde onderdelen scheiden.
- [x] Documentatie-audit, afhankelijkheden en open ontwerpvragen registreren.

### Fase 2 — ontbrekende telemetrie bepalen

- [x] Bestaande geregistreerde Sherlock-reviews per run, status/topicverdeling en completed-looptijd read-only ontsluiten.
- [x] Huidige queuevoorraad/leeftijd en parts, actieve tokenmetingen en lokale offers read-only tonen.
- [x] Gepubliceerde Sherlock-fiches en `queue_item_id` aan de huidige producerende run koppelen; generieke jobkoppeling volgt pas met het jobmodel.
- [ ] Materialisatiegroei, modelgebruik en intelligente backlog meten; toekomstige jobmetingen toevoegen.
- [ ] Telemetrycontract en basislijn vastleggen vóór capaciteitsbeslissingen.

Na bijwerken van de applicatie op bibib is de eerste kleine stap aan te roepen
via `./start_ariadne.sh telemetry`; deze PR voert geen deployment uit.
Zie [het telemetrycontract](telemetry.md) voor `--hours`, `--db`, snapshotsemantiek
en beperkingen. Het rapport gebruikt alleen bestaande tabellen, initialiseert
of migreert geen database en verandert geen runtime-state. Een rapport ontsluiten
is nog geen empirisch verzamelde productiebasislijn. Fase 2 blijft gedeeltelijk
open; de overige roadmapfasen veranderen niet.

Nog niet afleidbaar: niet-geregistreerde reviews, producenten van legacy/ongekoppelde fiches,
materialisatiegroei per tijdseenheid, daadwerkelijk modelgebruik en intelligente
jobbacklog. De ingressqueue is alleen een meetbare transportbacklog. Offers
bewijzen geen modelontvangst en een `running` run kan achtergelaten zijn.

De huidige runkoppeling gebruikt optionele `run_id`-transportmetadata bij
fichepublicatie. Schema 5 bewaart `sherlock_fiches` atomisch met de queue-insert;
de opgeslagen consumentenpayload blijft exact `schema_version`, `topic`, `date`
en `content`. Telemetry toont expliciet gekoppelde fiches en queue-IDs per run
en topic. Historische/ongekoppelde fiches krijgen geen geraden producent.
Er is nog geen `job_id`. Backend, plugin en actieve Sherlock-instructies moeten
na merge in die volgorde worden bijgewerkt; deze PR voert dat niet operationeel uit.

### Fase 3 — generiek job- en attemptmodel

- [ ] Stabiele jobs, rollen, status, timestamps en input/outputreferenties ontwerpen.
- [ ] Attempts, atomaire claims, expiry/lease/fencing of gelijkwaardig mechanisme vastleggen.
- [ ] Crash/herstart, verlopen claims, late resultaten en onzekere side effects specificeren.
- [ ] Nieuwe additieve SQLite-migratie implementeren en concurrency/herstel valideren.

Historisch achtergelaten `running` Sherlock-runs motiveren deze stap; de huidige
opslag heeft geen TTL of automatisch herstel. Een naïeve boolean of running-lock
is onvoldoende. Een verlopen claim mag niet ongecontroleerd overlappende uitvoering
of acceptatie van oude resultaten toelaten. Dit document kiest nog geen schema
of precieze lease-/fencing-semantiek.

### Fase 4 — generieke MCP/control-plane

- [ ] Claim/start, resultaat/finish en waar nodig fout/abandon ontwerpen en implementeren.
- [ ] Compacte auditmetadata, claimvalidatie en veilige concurrency opnemen.
- [ ] Retry-/idempotentiecontract per operatie expliciet maken.
- [ ] Bestaande Sherlock-tools aanvankelijk backwards compatible laten bestaan.

### Fase 5 — Sherlock naar generieke executor migreren

- [ ] Eerst uitsluitend Sherlock via het nieuwe jobmodel laten lopen.
- [ ] Drie topics, zoekworkflow, filtering, source-audit en fichepublicatie behouden.
- [ ] Batching en bestaand experimenteel safety-retrybeleid behouden.
- [ ] Source-audit en queue-output aan `job_id` koppelen en herstelgedrag bewijzen.

Andere rollen toevoegen nadat dit pad stabiel is; retries mogen geen nieuwe
rolkeuze of tweede job binnen dezelfde scheduled activatie veroorzaken.

### Fase 6 — Ariadne frequenter materialiseren

- [ ] Bestaande queue→parts-verwerking geschikt maken voor minstens uurlijk, mogelijk sneller lokaal gebruik.
- [ ] Snapshot-, lock-, provenance- en crashsafe implementatie zoveel mogelijk behouden.
- [ ] Exacte cadence meten/kiezen en lokale scheduling afzonderlijk invoeren.
- [ ] Afzonderlijk bepalen wanneer open parts worden aangeboden/sealed voor intelligent gebruik.

Deze fase moet vóór de eerste Sherlock/Leonardo-cyclus operationeel zijn; een
dagelijkse materialisatie mag geen urenoude oogst achter een klaarstaande job houden.

### Fase 7 — dispatcher introduceren

- [ ] Beginnen met topicrotatie als jobs en één scheduler.
- [ ] Harde start-/concurrencylimieten en pause/kill switch vastleggen.
- [ ] Bij geen nuttig werk geen intelligente job teruggeven.
- [ ] Daarna state-driven planning op expliciete voorwaarden verfijnen.

### Fase 8 — Leonardo-state en Leonardo-job

- [ ] Dossieridentiteit, rolling state en stateversies ontwerpen en opslaan.
- [ ] Hypotheses, claims, onzekerheden, open vragen en part/revisionreferenties opnemen.
- [ ] Begrensde Leonardo-job met expliciete input- en outputstate valideren.
- [ ] Geheugen-/missieprincipes uit het eerdere Leonardo-ontwerp hergebruiken.

Leonardo krijgt geen permanente worker; ieder vervolg krijgt zijn state opnieuw.

### Fase 9 — eerste volledige Sherlock/Leonardo-cyclus

- [ ] Bijvoorbeeld Sherlock topic 1 → topic 2 → topic 3 → Leonardo als experiment uitvoeren.
- [ ] Verse materialisatie, offers, stateovergang en provenance end-to-end controleren.
- [ ] Backlog en informatiewinst meten en prioriteiten daarop aanpassen.

De voorbeeldcyclus is geen permanente hardcoded policy. Later kunnen expliciete
missies, verificatie of beschikbare input een andere volgorde rechtvaardigen.

### Fase 10 — Kuifje

- [ ] Missies met `mission_id`, dossier, vraag, context, status en resultaat implementeren.
- [ ] Open gevalideerde missie beschikbaar maken als begrensde Kuifje-job.
- [ ] Resultaat mechanisch naar hetzelfde dossier terugrouteren, inclusief lege oogst/fouten.

Kuifje is een rol, geen aparte scheduler.

### Fase 11 — Striktland

- [ ] Drafts/claims en bronreferenties expliciet opslaan.
- [ ] Beperkte verificatiejobs met alleen noodzakelijk bewijs uitvoeren.
- [ ] Uitkomsten en kwaliteitslabels aan claim, draftversie en job koppelen.

### Fase 12 — Minos

- [ ] Alleen bij een relevant geregistreerd Striktland-probleem een Minos-job creëren.
- [ ] Problematische passage en noodzakelijk bewijs begrensd aanbieden.
- [ ] Correctie en provenance opslaan en daarna stoppen zonder regressielus.

### Fase 13 — capaciteits- en budgetbeleid

- [ ] Empirisch bepalen hoeveel scheduled capaciteit Weekendkrant mag gebruiken.
- [ ] Drempels voor extra schedulers en terugschakeling op nuttige backlog baseren.
- [ ] Voorrang/reservering voor handmatige persoonlijke arbeid vastleggen.
- [ ] Starts, attempts, allowance en contextbudget afzonderlijk bewaken.

Deze fase verfijnt de voorlopige harde limieten uit fase 7; zij is geen reden om
eerder onbeperkte capaciteit toe te staan of alle theoretische slots op te vullen.

### Fase 14 — weekafsluiting/eindredactie

- [ ] Dezelfde jobqueue tegen het weekend andere expliciete prioriteiten geven.
- [ ] Scouting waar nodig afremmen, dossiers afronden en open verificatie voltooien.
- [ ] Finale synthese en publicatiecriteria ontwerpen en invoeren.

Geen aparte permanente agents nodig; deadlinebeleid blijft een expliciete regel.

### Fase 15 — legacy orchestration opruimen

- [ ] Pas na bewezen nieuw pad de oude Sherlock-specifieke schedulerinterface opruimen.
- [ ] Oude doelontwerpen en README/architecture/roles naar bewezen runtime bijwerken.
- [ ] Historische documenten als historisch bewaren en compatibiliteitsafbouw documenteren.

## Open vragen

- Wat is de exacte frequentie van lokale Ariadne/materialisatie?
- Welke jobclaim/lease/fencing-semantiek voorkomt overlap en verouderde resultaten,
  en hoe verloopt crashherstel zonder onzekere effecten blind te herhalen?
- Wanneer moet een part aangeboden/sealed worden?
- Wanneer heeft een Leonardo-job voldoende nieuwe input en welke state krijgt hij?
- Hoe verhoudt een eerste vaste proefcyclus zich tot volledig state-driven dispatch?
- Wat is de maximale jobduur en hoe stopt of herstelt een overschrijding?
- Hoeveel schedulers zijn werkelijk nuttig bij de gemeten backlog?
- Welk concreet allowance-/budgetbeleid beschermt ook persoonlijke arbeid?
- Wat zijn de definitieve schemas voor Leonardo-state, dossiers, missies en drafts?

Deze punten zijn bewust geen fictieve beslissingen. Implementatiestappen moeten
de gekozen antwoorden, hun meetbasis en de gevolgen voor bestaande contracten
expliciet vastleggen.

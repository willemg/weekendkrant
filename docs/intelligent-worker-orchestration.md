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
| Geïmplementeerde fase-3-opslag | Lokale generieke jobs, afzonderlijke attempts, atomaire claims, vaste leases en fencing, conservatieve quarantaine en expliciete reconciliatie (schema 7); zonder workerintegratie; de aanvullende fase-4-control-plane staat hieronder. |
| Huidig beschreven operationeel ritme | Sherlock behandelt volgens zijn canonieke instructies één toegewezen topic per uurrun. De bestaande Ariadne `daily` ondersteunt herhaalde kwartierstarts; het voorlopige lokale croncontract is elke 15 minuten in `Europe/Brussels`, na handmatige invoering. Repository-instructies bewijzen op zichzelf geen actieve schedulerconfiguratie of deployment. |
| Gekozen doelrichting | Generieke scheduled executors krijgen per activatie maximaal één begrensde job met een door de backend gekozen rol. Persistente state draagt de redactionele continuïteit. Lokale Ariadne-materialisatie moet minstens uurlijk, mogelijk sneller, kunnen draaien. |
| Geïmplementeerde fase-4-control-plane | Expliciete generieke claim/finish/abandon/validate-tools, persistente operatiebevestigingen (schema 8), aparte operatorrecovery; lokaal getest; productie-invoering en geslaagde deployment-smoke op 14 oktober 2026 door de operator bevestigd. |
| Geïmplementeerde fase-5-adapter | Minimale Sherlock-jobproductie/topicrotatie, atomaire executorstart, contractsnapshots en gefencete bron-/fichewrites (schema 9); lokale validatie, operationele invoering nog open. |
| Nog niet geïmplementeerd | Dispatcher, Leonardo-state en -jobs, dossiers, missies, drafts, verificatie- en correctiejobs, capaciteitsbeleid en automatische eindredactie. |

Fase 3 voegt uitsluitend lokale jobopslag en schema 7 toe, zonder plugin, actieve
taakinstructies, cron, systemd of deployment te wijzigen. De bestaande runtimecontracten
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
| Job attempt | Eén geregistreerde uitvoeringspoging van dezelfde job, met eigen identiteit, claim, tijden en uitkomst. Een retry van uitvoering hoeft geen nieuwe job te worden. Een bevestigde toolretry met dezelfde operatie-identiteit maakt geen nieuwe attempt; zie fase 4. |
| Dispatcher | Deterministische backendlogica die op expliciete work/state en configureerbare regels beslist welke uitvoerbare job beschikbaar komt. |
| Persistent state/artifact | Opgeslagen bronmateriaal, concrete partrevisie, dossierstateversie, missie, draft, resultaat of audit met stabiele referenties; onafhankelijk van workergeheugen. |
| Dossier | Langlevend inhoudelijk onderzoek met eigen identiteit, state, hypotheses, claims, bronverwijzingen en eventuele missies. Een topic of fysieke part is niet automatisch een dossier. |
| Missie | Expliciete, begrensde onderzoeksvraag met `mission_id`, dossierkoppeling, context, status en resultaat; kan een Kuifje-job voeden. |

De huidige `sherlock_runs` zijn Sherlock-specifieke audit, geen generieke jobs.
De bestaande tabel `attempts` registreert Ariadne-runtimefouten en is evenmin
het toekomstige intelligente job-attemptmodel.

## Protocol en invarianten

Het conceptuele doelprotocol; het reeds geïmplementeerde fase-4-protocol staat in
[jobs.md](jobs.md#fase-4-protocol-identiteit-en-operation-receipts):

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
- Input, output, duur en toegestane acties zijn begrensd. Jobopslag en control-plane leggen referentie-, lease- en herstelgrenzen vast;
  inhoudelijke rol-/contextgrenzen volgen bij workerintegratie.
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

Fase 5 introduceert de minimale deterministische Sherlock-jobproductie met
topicrotatie en één scheduler, zodat de generieke executor concrete jobs krijgt.
Fase 7 bouwt daarop de algemene/state-driven dispatcher en verdere concurrency-/
policyregels. Voeg pas schedulers toe
als een aantoonbare backlog van nuttig intelligent werk dat rechtvaardigt.
Niet-uitvoerbaar werk en lege slots veroorzaken geen vervangende bezigheid.

## Ariadne: lokale deterministische verwerking

Ariadne blijft lokale deterministische software. Zij mag niet samenvatten,
relevantie beoordelen, semantisch dedupliceren, patronen herkennen of inhoudelijke
onderzoeksvragen bedenken. Zij mag persistente state beheren, input en output
koppelen, jobs beschikbaar maken en atomair claimen, workflowvoorwaarden en
harde budgetten controleren, dubbele claims voorkomen en resultaten mechanisch
naar expliciete dossiers, missies en jobs terugrouteren. Deze uitbreiding van
haar regietaak is doelontwerp, nog zonder geïntegreerde jobruntime.

De eerdere `daily`-verwerking eenmaal per dag om 10:00 is te traag voor deze
redactie. Als drie Sherlock-rondes nieuwe fiches leveren en daarna Leonardo
aan de slag moet, moet die oogst tijdig in lokale part/revision-state staan.

De gekozen doelrichting is **minstens eenmaal per uur materialiseren, mogelijk
duidelijk vaker**. Het onafhankelijke cadence-deel van fase 6 kiest voorlopig
**elke 15 minuten via lokale cron**. Ingest, materialisatieduur en gewenste
inputversheid moeten later uitwijzen of dat ritme passend blijft. Deterministisch
werk verbruikt geen intelligent scheduled slot. Deze PR wijzigt de productiecrontab
niet; zie [invoering en rollback](daily-runtime.md#croncontract-na-merge).

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
Deze tabel bewaart de historische audit, inclusief het toenmalige dagelijkse
croncontract. Het latere voorlopige kwartiercontract staat bij fase 6 en runtime.

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
- [x] Nieuwe materialisatiegroei door de tijd meten via bevestigde queue-aantallen en exacte bronbytes; historische onbekende tijden niet reconstrueren.
- [x] Beschikbaarheid van huidig modelgebruik onderzoeken en ontbrekende providerusage/allowance expliciet zichtbaar maken in read-only telemetry.
- [x] Huidige intelligente backlog onderzoeken en het ontbreken van een registratie van klaarstaand intelligent werk expliciet zichtbaar maken in telemetry.
- [ ] Modelgebruik en intelligente backlog meten; toekomstige jobmetingen toevoegen.
- [ ] Telemetrycontract en basislijn vastleggen vóór capaciteitsbeslissingen.

Na bijwerken van de applicatie op bibib is de eerste kleine stap aan te roepen
via `./start_ariadne.sh telemetry`; deze PR voert geen deployment uit.
Zie [het telemetrycontract](telemetry.md) voor `--hours`, `--db`, snapshotsemantiek
en beperkingen. Het rapport gebruikt alleen bestaande tabellen, initialiseert
of migreert geen database en verandert geen runtime-state. Een rapport ontsluiten
is nog geen empirisch verzamelde productiebasislijn. Fase 2 blijft gedeeltelijk
open; de overige roadmapfasen veranderen niet.

Nog niet afleidbaar: niet-geregistreerde reviews, producenten van legacy/ongekoppelde fiches,
historische materialisatiegroei zonder tijdprovenance, daadwerkelijk modelgebruik en intelligente
jobbacklog. De ingressqueue is alleen een meetbare transportbacklog. Offers
bewijzen geen modelontvangst en een `running` run kan achtergelaten zijn.

De huidige runkoppeling gebruikt optionele `run_id`-transportmetadata bij
fichepublicatie. Schema 5 bewaart `sherlock_fiches` atomisch met de queue-insert;
de opgeslagen consumentenpayload blijft exact `schema_version`, `topic`, `date`
en `content`. Telemetry toont expliciet gekoppelde fiches en queue-IDs per run
en topic. Historische/ongekoppelde fiches krijgen geen geraden producent.
Er is nog geen `job_id`-koppeling aan Sherlock-fiches. Backend, plugin en actieve Sherlock-instructies moeten
na merge in die volgorde worden bijgewerkt; deze PR voert dat niet operationeel uit.

Schema 6 voegt de kleine lokale `source_materializations`-provenance toe, atomisch
met succesvolle verwerking. Telemetry toont wanneer welke queue-items met hoeveel
bronbytes werden gematerialiseerd; eerdere archiefbronnen zonder tijd blijven
expliciet onbekend. Zie [het meetcontract](telemetry.md#materialisatiegroei).
Deze stap verandert geen uitvoeringscadence en introduceert geen modelgebruik of jobs.

De huidige usage-audit vindt geen betrouwbare model-ID, input/output/reasoning/
cacheusage of product-allowanceteller in Sherlock-state, MCP-contracten of de
beschikbare scheduled-taskmetadata. `model_usage` meldt daarom `unavailable`
met `null`-waarden en redenen; lokale deterministische Ariadne meldt
`not_applicable`. Bundeltokens, runtimes, reviews en toolcalls worden niet als
usage geïnterpreteerd. Alleen het onderzoek en de expliciete beschikbaarheids-
rapportage zijn gerealiseerd; daadwerkelijke gebruiksmetingen blijven open.
Zie [de usage-audit](telemetry.md#modelgebruik-beschikbaarheid-van-echte-metingen).

De backlog-audit vindt geen huidige registratie of lifecycle van klaarstaand
intelligent werk. `intelligent_backlog` meldt daarom `not_implemented` met
onbekende telling en oudste klaarzettijd. Ingress-pending, parts, offers en
gestarte Sherlock-runs worden niet tot intelligente opdrachten omgerekend.
Alleen onderzoek en expliciete beschikbaarheidsrapportage zijn gerealiseerd;
de werkelijke backlogmeting blijft open. Zie [de backlog-audit](telemetry.md#intelligente-backlog-nog-geen-werkregistratie).

### Fase 2.5 - systeemtest en operationele smoke test

Deze afzonderlijke fase is een expliciete gate vóór fase 3, naar aanleiding van
13 oktober 2026: groene unit-/integratietests bleken geen bewijs voor de werkelijke
Sherlock → ingress → SQLite → Ariadne-keten na een grote wijziging.

- [x] Reproduceerbare geïsoleerde systeemtest via echte HTTP-ingress en afzonderlijke ingress-/Ariadne-CLI-processen toevoegen.
- [x] Eén representatieve gekoppelde fiche exact eenmaal naar tijdelijke SQLite, bronarchief en week/topic/part met immutable revision materialiseren; processed en provenance controleren.
- [x] Herhaalde verwerking na bevestiging en lege runs zonder dubbele bronnen of gewijzigde revisies bewijzen.
- [x] Eén snelle handmatige testopdracht en de afgedekte/niet-afgedekte grenzen documenteren.
- [x] Veilige operationele smokeprocedure voor het werkelijk gedeployde pad vastleggen.
- [x] Verplichte relevante systeemtest en, bij deploymentwijzigingen, smoke na grote wijzigingen aan runtime, ingress, plugin, database of orchestratie canoniek vastleggen.
- [x] Operationele deployment smoke met een echte Sherlock-run via de herstartte productie-ingress bevestigen en het aangeleverde bewijs vastleggen.
- [x] Gate operationeel groen verklaren met de complementaire systeemtest en echte deployment smoke, vóór fase 3 start.

Zie [runtime/testcontract en operationele discipline](daily-runtime.md#systeemtest-en-operationele-gate)
voor de ene canonieke regel, testniveaus, opdracht, isolatie en beperkingen;
zie [deployment smoke](plugin-deployment.md#operationele-deployment-smoke) voor
het aanvullende productiepad. Lokale tests bewijzen geen deployment. Fase 3 mag
pas starten nadat de relevante systeemtest én deployment smoke aantoonbaar groen
zijn. Samen vormen die twee complementaire bewijzen de operationele gate:

- De geïsoleerde lokale systeemtest bewijst ingress → SQLite → Ariadne →
  part/revision → processed.
- De echte deployment smoke bewijst de werkelijk gepubliceerde externe route →
  productie-ingress → persistente fichewrite.

Een productie-item later door Ariadne zien verwerken is aanvullende observatie,
geen verplichte wachttijd voor een groene deployment smoke.
Bestaande fase-2-restpunten en andere roadmapstatussen blijven ongewijzigd.

Operationeel afgerond op 14 oktober 2026, op basis van het door de operator
bevestigde bewijs: 192 tests groen op bibib en een echte Sherlock-run via de
herstartte productie-ingress, met succesvolle runstart, source-audit,
fichepublicaties en runfinish. Dit is aangeleverd operationeel bewijs, geen
nieuwe productietest vanuit deze fase-3-implementatie; een exact productie-SHA
of afzonderlijk processed/revision-ID is hierbij niet aangeleverd.

### Fase 3 — generiek job- en attemptmodel

- [x] Stabiele jobs, rollen, status, timestamps en input/outputreferenties ontwerpen en implementeren.
- [x] Afzonderlijke attempts, atomaire claims en expliciete vaste lease-/expiry-/fencing-semantiek vastleggen en implementeren.
- [x] Crash/herstart, verlopen claims, late resultaten en onzekere side effects specificeren en testen.
- [x] Nieuwe additieve SQLite-migratie implementeren en concurrency/herstel valideren.

Zie [jobopslag en herstelcontract](jobs.md) voor ontwerp, API, grenzen en tests.
Schema 7 maakt uitsluitend lokale opslag beschikbaar. De voorlopige defaultlease
is 3600 seconden, een conservatieve veiligheidsgrens voor de eerste meetfase,
geen gemeten optimum of gewenste jobduur. Een gezonde job richting één uur levert
juist meetinformatie voor later lease-/capaciteitsbeleid. De lease blijft per job
configureerbaar tot 86400 seconden, zonder heartbeat/renewal.
Expiry blokkeert de job;
een nieuwe attempt vereist expliciete reconciliatie met bewijs van gestopte
executor en bekende effecten. Attempt-ID plus unieke token fence resultaatacceptatie.
Er is geen automatische retry van onzekere side effects en geen exactly-once-
belofte voor externe publicatie. Een unieke activation-ID begrenst elke activatie
tot één attempt/job. Bestaande Sherlock-runs en Ariadne-attempts blijven intact;
De control-plane is in fase 4 toegevoegd; dispatcher en migratie van Sherlock
blijven latere fasen.
De volledige suite en de bestaande geïsoleerde systeemtest moeten groen zijn;
de implementatie is geen productie-upgrade of operationele jobintegratie.

### Fase 4 — generieke MCP/control-plane

- [x] Claim/start, resultaat/finish en waar nodig fout/abandon ontwerpen en implementeren.
- [x] Compacte auditmetadata, claimvalidatie en veilige concurrency opnemen.
- [x] Retry-/idempotentiecontract per operatie expliciet maken.
- [x] Bestaande Sherlock-tools aanvankelijk backwards compatible laten bestaan.

Zie [het fase-4-protocol](jobs.md#fase-4-protocol-identiteit-en-operation-receipts)
voor velden, fencing, transportretries, persistente receipts en afzonderlijke
operatorauthenticatie. Claim kiest alleen een aangeleverd job-ID. Sherlock blijft
op de specifieke runtime; geen dispatcher, scheduler- of capacitywijziging.
Implementatie en lokale backendtests zijn gerealiseerd. Na merge van PR #48 heeft
de operator op 14 oktober 2026 de productie-invoering en geslaagde deployment-smoke
bevestigd, na het starten van de tunnel. Dit is aangeleverd operationeel bewijs,
geen nieuwe controle vanuit deze documentatiecorrectie. Een exact productie-SHA
of nieuwe afzonderlijke bewijs-ID is niet geregistreerd. De actieve Sherlock-
instructies gebruikten de nieuwe generieke tools toen nog niet.

De testlagen blijven gescheiden: de Python-suite en systeemgate op bibib zijn
Node-vrij; JavaScript-pluginchecks en de expliciete bridge/backend-developmenttest
draaien afzonderlijk. Het gepubliceerde Sites → tunnel → backend-pad vereist de
bestaande deployment-smoke. Zie [testlagen](jobs.md#testlagen-en-bewijsgrenzen).

### Fase 5 - Sherlock naar generieke executor migreren

- [x] Minimale deterministische Sherlock-jobproductie/topicrotatie voor één scheduler implementeren, met concrete immutable rol-, input- en outputcontractreferenties.
- [x] Jobproductie en claim atomair aan dezelfde aangeleverde scheduled activation koppelen; retries behouden operatie-/activationidentiteit en maken geen dubbele job of tweede attempt.
- [x] Generieke executorinstructie en eerst uitsluitend de Sherlock-adapter implementeren.
- [x] Drie topics, zoekworkflow, filtering, source-audit en fichepublicatie behouden.
- [x] Batching en bestaand experimenteel safety-retrybeleid behouden in de nieuwe rol-/executorcontracten.
- [x] Source-audit en queue-output via run/attempt aan job_id koppelen en herstelgedrag lokaal bewijzen.
- [ ] Backend/schema 9 en Sites-plugin operationeel invoeren en nieuwe deployment-smoke vastleggen.
- [ ] Stabiele occurrencecontext van de echte scheduler controleren en actieve instructies bewust naar de generieke executor omschakelen; pas daarna één begeleide echte job bewijzen.

Zie [Sherlock-executor](sherlock-executor.md) voor protocol, invarianten, tests en
invoervolgorde. De bestaande scheduler blijft gepauzeerd; de PR voert geen
productie-upgrade, Sites-publicatie, taakwijziging of heractivering uit. De backend
bindt caller-supplied occurrencecontext persistent; native platforminjectie is
nog geen geleverd bewijs. De executor stopt als betrouwbare occurrencecontext
ontbreekt. Eén running/blocked Sherlock-job blokkeert verdere productie, ook over
verschillende activaties heen. Een lege activatie blijft leeg. Expliciet herstelde
jobs behouden topic/opdracht en krijgen een nieuwe attempt en run.

Fase 4 blijft de generieke expliciet-job-ID-control-plane. Fase 5 voegt daarnaast
één specifieke startadapter toe en wacht niet op de algemene dispatcher van
fase 7. Andere rollen volgen pas nadat dit pad operationeel bewezen stabiel is.

### Fase 6 — Ariadne frequenter materialiseren

- [x] Bestaande queue→parts-verwerking voor herhaalde kwartierstarts valideren, inclusief lege runs en echte procesoverlap zonder dubbel materiaal.
- [x] Bestaande snapshot-, flock-, provenance-, retry- en crashsafe implementatie behouden.
- [x] 15 minuten als voorlopige operationele croncadence documenteren, met handmatige invoering en rollback.
- [ ] Productiecrontab handmatig invoeren en de voorlopige cadence empirisch evalueren.
- [ ] Afzonderlijk bepalen wanneer open parts worden aangeboden/sealed voor intelligent gebruik.

Alleen dit onafhankelijke cadence-deel wordt vervroegd uitgevoerd, zonder de
job-/dispatcherfasen af te wachten. De bestaande runtime volstaat; er komen geen
nieuwe jobs, modelcalls of offers/sealing bij. Tests en documentatie bewijzen
geschiktheid, niet een al uitgevoerde productie-installatie. Fase 6 blijft deels open.

Deze fase moet vóór de eerste Sherlock/Leonardo-cyclus operationeel zijn; een
dagelijkse materialisatie mag geen urenoude oogst achter een klaarstaande job houden.

### Fase 7 — algemene/state-driven dispatcher introduceren

- [ ] Voortbouwen op de minimale Sherlock-jobproductie en één scheduler uit fase 5; algemene workselectie over beschikbare jobs/state toevoegen.
- [ ] Harde start-/concurrencylimieten en pause/kill switch vastleggen.
- [ ] Bij geen nuttig werk geen intelligente job teruggeven.
- [ ] State-driven planning op expliciete voorwaarden verfijnen.

Fase 7 generaliseert selectie, concurrency en policy nadat Sherlock zelfstandig
via fase 5 kan draaien; zij is geen voorwaarde meer voor die eerste migratie.

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

- Blijft de voorlopige 15-minutencadence passend volgens de werkelijke materialisatietijden en ingest?
- Hoe wordt het gekozen conservatieve lease-/fencing- en reconciliatiecontract
  door latere publicatieadapters voor externe effecten afgedwongen?
- Wanneer moet een part aangeboden/sealed worden?
- Wanneer heeft een Leonardo-job voldoende nieuwe input en welke state krijgt hij?
- Hoe verhoudt een eerste vaste proefcyclus zich tot volledig state-driven dispatch?
- Welke leaseduur binnen het fase-3-bereik past per rol, en hoe wordt een executor
  operationeel gestopt voordat recovery veilige heruitvoering kan bevestigen?
- Hoeveel schedulers zijn werkelijk nuttig bij de gemeten backlog?
- Welk concreet allowance-/budgetbeleid beschermt ook persoonlijke arbeid?
- Wat zijn de definitieve schemas voor Leonardo-state, dossiers, missies en drafts?

Deze punten zijn bewust geen fictieve beslissingen. Implementatiestappen moeten
de gekozen antwoorden, hun meetbasis en de gevolgen voor bestaande contracten
expliciet vastleggen.

# Rollen

## Runtimecontracten (fase 8.5)

Er is momenteel één echte scheduled intelligente worker: de generieke executor.
Sherlock, Leonardo, Kuifje, Striktland, Minos en Einstein zijn rollen, geen
aparte agents of scheduled workers. De executor kent uitsluitend het generieke
claim-, validate- en finishprotocol; inhoudelijke workflow en toolgebruik komen
uit de contractsnapshot van de geclaimde job.

| Begrip | Betekenis |
| --- | --- |
| Executor | De enige generieke scheduled intelligente worker |
| Job | Eén begrensde intelligente run met één rol, immutable context en outputcontract; schedulingeenheid |
| Attempt | Eén uitvoeringspoging van dezelfde job |
| Mission | Eén immutable onderzoeksvraag binnen een Kuifje-job, geen schedulingeenheid |
| Activation | Eén scheduled kans om maximaal één job uit te voeren |
| Role | Inhoudelijke runtime-instructies voor één type werk |
| Producer/adapter | Backendcomponent die jobs produceert en/of bindt |
| Role contract | Versioned repository-artifact voor nieuwe jobs |
| Contractsnapshot | Immutable exacte contractinhoud van een concrete job |
| Ariadne/backendregie | Deterministische laag die jobs/state beheert en contractsnapshots aan jobs bindt |

`roles/*.md` zijn runtime-artifacts, niet alleen documentatie. De canonieke
bestanden voor nieuwe jobs zijn [Sherlock](../roles/sherlock.md),
[Sherlock-output](../roles/sherlock-output.md), [Leonardo](../roles/leonardo.md)
en [Leonardo-output](../roles/leonardo-output.md). `docs/agents/` bevat de echte
runtime-artifact [executor/instructions.md](../executor/instructions.md);
[executor.md](agents/executor.md) is menselijke documentatie.

Nieuwe Sherlock-productie leest via `SherlockProducer.prepare()` de actuele
bestanden buiten de schrijflock; Leonardo leest ze bij nieuwe
`LeonardoStore.enqueue()` vóór de schrijflock. De gedeelde loader leest maximaal
65.537 bytes en accepteert niet-lege UTF-8 van maximaal 65.536 bytes per contract.
SHA-256 beschrijft exact de gelezen bytes, zonder newlineconversie of trimmen.
Sherlock bewaart content-addressed contracten; Leonardo bewaart beide teksten
in zijn immutable assignment en de outputref in de job. De rolref wordt bij
bind uit uitsluitend de persistente snapshot berekend.

Wijzigingen aan een role file beïnvloeden uitsluitend toekomstige jobs. Vanaf
jobaanmaak is de contractsnapshot autoritatief, ook na wijziging, verwijdering
of beschadiging van deploymentbestanden. `bind()`, ready/recovery en activation
replay lezen geen actuele role files. Ook directe pause-, concurrency- en
blocked-weigering heeft geen role-file-I/O nodig. Alleen wanneer nieuwe
Sherlock-productie werkelijk wordt overwogen, vindt lazy preparation plaats.
De executor leest zelf nooit rolbestanden uit de repository.


### Runtimecontracthygiëne en contextisolatie

De role- en outputcontracten zijn productie-input voor een worker, geen verkorte
architectuurdocumentatie. Daarom staan alle natuurlijke-taalinstructies in deze
contracten in het Nederlands. Exacte technische identifiers, toolnamen,
veldnamen, enumwaarden en letterlijke externe foutmeldingen blijven in hun
contractuele vorm staan.

Een rolecontract moet epistemisch gesloten zijn. Een worker krijgt alleen
verwijzingen naar context die hij werkelijk kan waarnemen: aangeleverde input,
expliciet beschikbare tools en velden, en de grenzen van zijn eigen opdracht.
Uitleg over waarom een regel bestaat, welke andere rol later iets zal doen,
backendtopologie, historische incidenten en ontwikkelmotivatie horen hier in de
documentatie en niet in de runtimeprompt.

Dit voorkomt niet alleen lokale promptvervuiling maar ook contaminatie doorheen
de keten. Het risico lijkt op het fluisterspel uit een jeugdbeweging: één
oorspronkelijke zin wordt van persoon tot persoon doorgegeven en komt vervormd
terug. In een agentketen is dat gevaarlijker omdat iedere tussenstap de ontvangen
context als legitieme taakinput kan behandelen. Een architectuurhint in een
rolecontract kan zo eerst een inferentie in state worden, daarna een
onderzoeksmissie sturen, vervolgens de bronselectie beïnvloeden en uiteindelijk
als nieuwe inhoud terugkeren. Tegen dan is de oorspronkelijke herkomst van het
frame moeilijk zichtbaar.

Daarom bewaken we naast bronprovenance ook de herkomst van framing. Runtimeprompts
bevatten alleen operationele instructies voor de huidige job; architectuur,
motivatie en historische lessen blijven in `docs/`.


Een bijkomend risico is **statuspromotie**. Informatie die bij de eerste worker
slechts ruis, bijkomstige formulering of impliciete architectuurcontext was, kan
na één transformatie in een state of missie voor de volgende worker de status van
legitieme taakcontext krijgen. De oorsprong en oorspronkelijke onzekerheidsstatus
zijn dan niet meer zichtbaar. Zo kan een keten ontstaan als:

`ruis in instructie → inferentie in state → onderzoekscontext → gerichte bronselectie → nieuw bewijsachtig materiaal`

Daarbij vervormt niet alleen de inhoud, maar ook het soort informatie dat een zin
geacht wordt te zijn. Wat begon als niet-inhoudelijke context kan onderweg als
premisse, onderzoeksvraag of quasi-bewijs worden behandeld. Daarom is het niet
voldoende om alleen bronrefs technisch correct te bewaren: ook framing die geen
inhoudelijke provenance heeft, moet uit persistente inhoudelijke artifacts en
missies geweerd worden.


### Samengestelde-contextaudit

Een rolefile wordt nooit geïsoleerd beoordeeld. Voor iedere bestaande of nieuwe
intelligente rol reconstrueren we vóór activering de **werkelijke context die de
worker ontvangt** en lezen we die alsof er geen andere kennis over Weekendkrant
bestaat. Minimaal worden samen bekeken:

1. de generieke executorinstructies die vóór de rol worden uitgevoerd;
2. het concrete jobpakket zoals de producer of adapter het aanlevert, inclusief
   claim, `role`, `input`, `result_ref` en technische refs;
3. het volledige rolecontract;
4. het volledige outputcontract;
5. alle Weekendkrant-toolnamen, descriptions en input/outputschema's die voor de
   worker zichtbaar zijn;
6. de inhoudelijke artifacts die werkelijk als input kunnen verschijnen, zoals
   state, parts, missies, geselecteerde onderzoeksresultaten en recallresultaten.

De centrale vraag is:

> **Is deze samengestelde context intern consistent en volledig begrijpelijk
> zonder kennis van iets erbuiten, en zonder dat externe architectuurcontext als
> inhoudelijke kennis kan binnensijpelen?**

De audit controleert daarbij expliciet:

- **referentiële geslotenheid:** ieder begrip waarop een instructie steunt is in
  de samengestelde context gedefinieerd of is een exact zichtbaar technisch
  identifier;
- **semantische consistentie:** verschillende lagen geven hetzelfde veld, begrip
  of handeling geen strijdige betekenis;
- **epistemische zuiverheid:** transportmetadata, identifiers, opslagdetails,
  architectuur en ontwikkelhistoriek worden niet als inhoudelijk bewijs of
  redactionele kennis aangeboden;
- **statusbehoud:** een technische ref, eerdere samenvatting of rationale krijgt
  niet stilzwijgend de status van primair bewijs;
- **toolgrens:** de rol benoemt welke Weekendkrant-tools voor haar huidige job
  bedoeld zijn; gedeelde toolbeschrijvingen blijven rolneutraal en leggen geen
  verantwoordelijkheden van andere rollen uit;
- **outputsluiting:** ieder verplicht outputveld is lokaal verklaard en kan
  uitsluitend met de aangeleverde input en toegestane tools correct worden
  ingevuld;
- **taalhygiëne:** natuurlijke-taalinstructies zijn Nederlands; alleen exacte
  technische identifiers, schemawaarden en letterlijke externe meldingen blijven
  in hun contractuele vorm;
- **geen handmatige promptversies:** role- en outputcontracten krijgen geen
  `v1`, `v2` of vergelijkbare handmatige versielabels. Gitgeschiedenis,
  contractsnapshot en SHA-256 identificeren de concrete contractinhoud.
  Machinevelden zoals `schema_version` blijven bestaan wanneer het dataschema
  ze werkelijk vereist.

Een nuttige eindtest is de **koude-worker-test**: geef een reviewer alleen de
hierboven samengestelde context en vraag welke informatie inhoudelijk bewijs is,
welke informatie alleen identiteit/provenance is, welke tools gebruikt mogen
worden en welk resultaat verwacht wordt. Als daarvoor uitleg uit onze
architectuurdocumentatie nodig is, is het runtimecontract nog niet gesloten.

Deze audit is voortaan een ontwerpvoorwaarde vóór runtime-invoering van nieuwe
rollen. Dat geldt in het bijzonder voor de geplande rollen Striktland, Minos en
Einstein: eerst hun volledige jobpakket, toolsurface, rolecontract en
outputcontract samen ontwerpen en als één context auditen, pas daarna de rol
activeren.

### Audit van de huidige rollen

De huidige Sherlock-, Leonardo- en Kuifje-contexten zijn volgens deze methode
naast hun producer-output en gedeelde toolsurface gelegd.

**Sherlock:** `input.topic` en `input.date` zijn de enige inhoudelijke
jobvelden; het rolecontract gebruikt voortaan expliciet `input.date` in plaats
van zelf een kalenderdatum af te leiden. Het contract bevat een expliciete
Weekendkrant-toolgrens. Het outputcontract beschrijft alleen de vereiste uitkomst
en transporthandeling, niet de backendarchitectuur.

**Leonardo:** de inhoudelijke basis is state, aangeleverde parts en geselecteerde
`research_results`. `dossier_id`, versienummers, tokenizer en refs worden
expliciet als identiteit, formaat of provenance behandeld en niet als bewijs.
Het technische veld `kuifje_missions` wordt lokaal verklaard als naam voor
onderzoeksvoorstellen, zonder kennis van een andere rol te vereisen. De
`queue:<id>`-vorm is lokaal gedefinieerd zonder opslagimplementatie als
inhoudelijke context. Role- en outputcontract staan zowel in de immutable
assignment als bovenaan het jobpakket; die redundantie is momenteel exact en
dus consistent, maar mag bij latere refactors nooit twee verschillende
contractinhouden opleveren.

**Kuifje:** `input.missions` is de ordered lijst van 1..4 zelfstandige missies
binnen één job/run en één topic. `input.date` geeft expliciet de bevroren
datum van opdrachtvoorbereiding in Europe/Brussels; iedere fiche gebruikt exact
die waarde. De publicatiedatum van de bron is uitsluitend inhoud in `content`.
De datum die routing of ordening bepaalt mag nooit door de worker uit
bronmetadata of een eigen klok worden geraden.
Het rolecontract noemt exact de missionvelden die werkelijk worden
aangeleverd. `question`, `rationale` en `scope` sturen het onderzoek;
`topic` begrenst onderwerp en publicatiemetadata; de overige identifiers en
refs zijn uitsluitend identiteit/provenance. Het outputcontract verklaart de
rolnaam en het technische veld `kuifje_result` lokaal. Er is een expliciete
Weekendkrant-toolgrens en er wordt geen eerdere dossierinhoud verondersteld.
De samengestelde context moet ook fichepublicatie per `mission_id`, limieten per
missie, claimvalidatie bij missiegrenzen en één volledig ordered
`mission_results`-jobresultaat lokaal verklaren. Mogelijke toolresponses voor
claimverlies, conflict en onzeker transport worden samen met het concrete
schema-2-jobpakket beoordeeld; generieke descriptions blijven rolneutraal.

De gedeelde MCP-toolsurface is eveneens onderdeel van deze audit. De descriptions
van generieke tools zijn daarom rolneutraal gemaakt; rolspecifieke payloadregels
staan in role- en outputcontracten. De huidige plugin exposeert technisch nog
enkele rolspecifiek benoemde tools aan alle workers. Zolang de toolsurface niet
per job kan worden gescopeerd, vormt de expliciete allowlist in ieder rolecontract
de grens: niet-genoemde Weekendkrant-tools behoren niet tot die opdracht.

## Sherlock — de speurneus

Sherlock is een inhoudelijke rol van de generieke executor.

Sherlock levert fiches via de Weekendkrant Ingress MCP-plugin aan de HTTPS-API.
SQLite bewaart de transportqueue; GitHub is geen transportqueue. Het dagelijkse
consumentencontract heeft exact `schema_version: 1`, `topic: 1|2|3`, een Belgische
ISO-kalenderdatum en niet-lege Markdown in `content`. De oude Git-header en
`closed`-melding worden niet meer gebruikt. Sherlock behandelt per geclaimde
job precies één door de backend toegewezen topic, met de reeds gebonden run
en claim.
Zie de [canonieke Sherlock-instructies](../roles/sherlock.md). Ariadne verwerkt de
ontvangen fiches via de bestaande deterministische `daily`. Het voorlopige lokale
croncontract is elke 15 minuten in `Europe/Brussels`, na handmatige invoering;
de repository wijzigt geen actieve scheduled taak of productiecrontab.

### Voorlopige verantwoordelijkheden

- periodiek het web afzoeken naar nieuwe ontwikkelingen;
- werken over een vaste maar uitbreidbare lijst interessegebieden;
- een eerste lichte triage proberen uit te voeren;
- per relevante vondst de oorspronkelijke bron bewaren;
- waar haalbaar de bron compact en feitelijk samenvatten;
- waar haalbaar een eenvoudige onderwerpindeling bewaren;
- de oogst via HTTPS aan de ingress-API afleveren via de MCP-plugin;
- lokale datums en redactionele ISO-weken bepalen in `Europe/Brussels`.

De producer-API en Ariadne-consument zijn beschikbaar. Het lokale
[queuecontract](daily-runtime.md) bepaalt validatie en lege oogst. De
[oude instructieaanvulling](sherlock-dagafsluiting.md) is historische referentie;
het Git-afsluitcontract is niet meer operationeel. De runtimecontracten wijzigen
geen actieve scheduled taak.

### Onderzoeksgebieden

De inhoudelijke scope hieronder is het **zoekterrein**, niet een verplicht uitvoerschema. Iedere huidige Sherlock-uurrun onderzoekt uitsluitend het toegewezen topic. De vijf nieuwstaken uit de oorspronkelijke opzet zijn historische inspiratie voor de onderwerpen en signalen hieronder, geen beschrijving van de actuele runtime.

Tijdens de observatiefase onderzoeken we welke onderdelen een actieve taak werkelijk betrouwbaar kan combineren. Als bijvoorbeeld brede zoekdekking, compacte samenvatting en cross-domain signalering samen te veel blijken, vereenvoudigen we Sherlock in plaats van Ariadne afhankelijk te maken van fragiele output.

Sherlock zoekt niet alleen naar losse gebeurtenissen, maar vooral naar ontwikkelingen die structureel iets kunnen veranderen.

#### Democratie, governance en collectieve besluitvorming

Wereldwijd zoeken naar betekenisvolle ontwikkelingen in onder meer:

- staten en gemeenten;
- coöperaties en bedrijven;
- vakbonden en verenigingen;
- gemeenschappen en commons;
- online groepen en andere vormen van zelforganisatie.

Bijzondere aandacht gaat naar terugkerende mechanismen, machtsdeling, loting, directe participatie, deliberatie, participatieve budgettering, werknemerszelfbestuur, schaalbaarheid en omstandigheden waaronder institutionele experimenten slagen of mislukken.

Sherlock zoekt bewust verder dan de gebruikelijke landen en instellingen en neemt waar nuttig ook onderbelichte en niet-Engelstalige bronnen mee.

#### Wetenschap en filosofie

Zoeken naar mogelijke structurele of paradigmatische verschuivingen, met bijzondere aandacht voor:

- nieuwe instrumenten of datasets die gevestigde modellen onder druk zetten;
- reproduceerbare anomalieën;
- convergerend bewijs voor nieuwe fundamentele theorieën;
- grote methodologische verschuivingen;
- krachtige nieuwe syntheses die bestaande aannames of disciplines verbinden.

Sherlock moet onderscheid proberen te bewaren tussen een geïsoleerde anomalie, een interessante spanning, een opkomend alternatief raamwerk en een geloofwaardige kandidaat-paradigmaverschuiving. Hype en conclusies op basis van één paper krijgen weinig gewicht.

#### Artificiële intelligentie

Zoeken naar structurele ontwikkelingen in onder meer:

- modelcapaciteiten en architecturen;
- training- en inferentieparadigma's;
- AI-ontworpen hardware en software;
- agents en robotica;
- wetenschappelijke toepassingen;
- organisatorische adoptie;
- institutionele en maatschappelijke effecten;
- feedbacklussen tussen AI, onderzoek, hardware, organisaties en samenleving.

Productlanceringen en benchmarknieuws zijn alleen interessant wanneer ze een echte drempel overschrijden of deel blijken van een breder patroon. Bijzondere aandacht gaat naar beperkingen die verdwijnen, onafhankelijke herhaling van nieuwe capaciteiten, AI die AI-onderzoek of hardwareontwikkeling versnelt, onverwachte toepassingsgebieden en veranderingen in de organisatie van werk of instituties.

#### Cross-domain patronen

De huidige taken bevatten naast de drie inhoudelijke domeinen ook een expliciete redactionele laag. Sherlock moet daarom tijdens zijn eerste triage signaleren wanneer ontwikkelingen mogelijk relevant zijn voor meerdere domeinen, bijvoorbeeld:

- hetzelfde mechanisme dat tegelijk in governance en AI opduikt;
- een wetenschappelijke ontwikkeling met institutionele gevolgen;
- feedbacklussen die verschillende systemen versterken of afremmen;
- meerdere onafhankelijke gebeurtenissen die samen een structurele verschuiving kunnen vormen;
- nieuwe informatie die een eerder signaal verzwakt, corrigeert of juist versterkt.

Sherlock hoeft daar nog geen eindinterpretatie van te maken. Cross-domain signalering is bovendien voorlopig een **nice-to-have**: als dit de betrouwbaarheid van verzamelen en bronvast samenvatten aantast, laten we die taak volledig aan Leonardo over.

#### Selectieprincipe

Routine-nieuws, publicatiechurn en productruis hoeven niet automatisch mee. Sherlock geeft voorrang aan materiaal dat ten minste één van deze eigenschappen heeft:

- structurele betekenis;
- onverwachte convergentie;
- mogelijke trendbreuk;
- relevante feedbacklus;
- nieuwe voorwaarde voor succes of falen;
- correctie of tegenspraak van een eerder signaal;
- voldoende bronkwaliteit om later door Leonardo en Striktland gebruikt te worden.

Belangrijke beweringen moeten zoveel mogelijk terug te voeren zijn op primaire of oorspronkelijke bronnen, aangevuld met sterke secundaire bronnen wanneer die verificatie, context of tegenspraak toevoegen.

### Niet doen

Sherlock moet nog geen weekendartikel schrijven en geen brede syntheses maken. Hoe meer interpretatie Sherlock toevoegt, hoe groter het risico dat latere agents een vroege inferentie als feit behandelen.

De output moet uiteindelijk bruikbaar genoeg zijn om deterministisch door Ariadne verwerkt te worden, maar het precieze formaat wordt pas gekozen nadat we meerdere weken echte Sherlock-output hebben gezien. We ontwerpen Ariadne dus **naar de feitelijke output van Sherlock**, niet andersom.

## Ariadne — de draadlegger

Ariadne is geen agent maar een deterministisch script, bedoeld om via cron op een Raspberry Pi te draaien.

Geïmplementeerd zijn de SQLite-backlogconsument, cross-day week/topic-parts
met immutable revisies en exact bronarchief, en de
[dagelijkse deterministische verwerking](daily-runtime.md).

### Verantwoordelijkheden

- pending fiches tot en met vandaag in Europe/Brussels in één snapshot verwerken;
- oude pending fiches automatisch meenemen zonder afzonderlijke herstelmodus;
- via lokale cron elke 15 minuten starten volgens het voorlopig handmatig in te voeren croncontract; nul fiches is succes;
- queue-items na geslaagde output en provenance atomisch processed markeren;
- nieuwe Sherlock-output herkennen;
- fichetopic valideren tegen de vaste catalogus `1`, `2`, `3`;
- mechanisch groeperen per onderwerp;
- tokenaantal meten met `tiktoken==0.12.0`, encoding `cl100k_base`;
- lokale draden maken;
- maximaal 30.000 geserialiseerde brontokens per draad bewaken; deze
  deterministische partgrens blijft bruikbaar, maar is niet langer bedoeld als
  afleiding van een definitieve totale Leonardo-contextgrens. De huidige
  schema-12/backend gebruikt een ruime technische fail-safe van 1.048.576
  lokale tokens en 8 MiB voor startinput plus recall per attempt, om Leonardo's
  contextgebruik te karakteriseren;
- verwerkingsstatus en provenance in een lokale SQLite-database administreren;
- mislukte pogingen zichtbaar bewaren terwijl queue-items pending blijven;
- alle runtime-informatie via de centrale Python-`logging`configuratie schrijven,
  met levels en rotatie naar `/home/weekendkrant/logs/`.

Tijdens de observatiefase zijn Ariadnes draden afgeleide werkproducten. Ze hoeven niet
terug naar GitHub en moeten uit dezelfde ingress reproduceerbaar opnieuw opgebouwd
kunnen worden.
`daily` gebruikt een lokaal niet-blokkerend slot buiten de applicatierepository en
voert geen Git-operaties uit. De fiche-datum blijft provenance. Late arrivals
groeien de open part van hun ISO-week/topic via een nieuwe revisie; bestaande
bronvolgorde en eerdere geregistreerde revisies blijven intact. Overflow sluit
een part definitief. Er is geen dagafsluit-gating, zondagjob,
weekrapport of automatische retentie. Bestaande data blijft behouden.

### Geheugenbeheer en gepland budgetbeheer

Ariadne/backend beheert Leonardo's persistente dossierstate en contextaanbieding:
state letterlijk opslaan en versioneren, omvang meten, concrete immutable
partrevisies aanbieden en claimgebonden historical recall auditen. Ook het
vullen van open bronparts over daggrenzen is geïmplementeerd. Het
[geheugenontwerp](leonardo-memory-and-orchestration.md) blijft richtinggevend
voor verdere uitbreiding; providerusage, kostenafrekening en capaciteitsbeleid
zijn nog gepland.

De fase-12-keten bewaart afzonderlijke immutable Kuifje-missies en hun
job-/attemptbinding. Kuifjes bronfiches doorlopen de bestaande ingress- en
partketen. Daarnaast levert expliciete selectie van één terminale Kuifje-job en
attempt alle missie-uitkomsten als aanvullende `research_results` aan Leonardo,
ook bij lege oogst of een terminale mislukking. Deze context verruimt
`processed_refs` niet. Automatische resultaatselectie en dossierroutering zijn
niet geïmplementeerd. Zie het [fase-12-contract](phase-12-kuifje.md).

Leonardo beslist over betekenis, compressie en inhoudelijke verbanden; Ariadne
controleert formaat, omvang, koppelingen en toegestane acties.

### Niet doen

Ariadne mag niet:

- samenvatten;
- relevantie beoordelen;
- semantisch dedupliceren;
- verbanden leggen;
- bronnen interpreteren;
- ontbrekende metadata raden.

Ariadne vlecht draden; ze denkt niet.

## Leonardo — de schrijver en synthesizer

Leonardo krijgt expliciet samengestelde context met nieuwe bronparts en de
geldige compacte dossierstate, of een reevaluation-opdracht zonder nieuwe parts.
Gerichte historical recall is binnen dezelfde job beschikbaar. Optioneel bevat
zijn assignment expliciet geselecteerde Kuifje-uitkomsten in `research_results`;
die zijn aanvullende onderzoekscontext, geen primair bronbewijs. Continuïteit
zit in de opgeslagen state en bronnen.

Leonardo kan naast een succesvolle state maximaal vier afzonderlijke
Kuifje-missies voorstellen. De backend valideert en bewaart die atomair als
immutable artifacts en bundelt ze binnen hetzelfde topic tot één Kuifje-job/run.
Missies en operationele administratie horen niet in Leonardo's dossierstate.
Dossierstate, recall, missievoorstellen en expliciete resultaatretour zijn
geïmplementeerd; automatische Leonardo-productie en resultaatroutering blijven
buiten dit contract.

Leonardo onderzoekt primair de inhoudelijke/structurele ruimte: welke informatie
samenhangt, welke onafhankelijke sporen binnen een topic bestaan, welke claims en
hypotheses elkaar ondersteunen of tegenspreken, waar bron- of perspectieflacunes
zitten en welke dossierverbanden of begrensde onderzoeksvragen relevant zijn.
Een topic is niet automatisch een dossier.

Een langlevend of bijgewerkt dossier en rolling dossierstate bewaren continuïteit.
Leonardo mag een vorige state als compacte context voor zijn volgende structurele
analyse gebruiken. `previous_version` en opeenvolgende stateversies maken hem niet
verantwoordelijk voor longitudinale trend- of evolutieanalyse; die hoort later
bij Einstein. Datums, volgorde, causaliteit en andere temporele bronfeiten mag
Leonardo wel gebruiken om het aangeboden materiaal correct te begrijpen.

### Verantwoordelijkheden

- verbanden leggen;
- gebeurtenissen in context plaatsen;
- inhoudelijke en structurele patronen herkennen;
- tegenstrijdigheden zichtbaar maken;
- op dossier-/verhaalniveau de breedte en onafhankelijkheid van bronnen en perspectieven bewaken;
- bij ontbrekende relevante spreiding of onafhankelijke bevestiging een begrensde Kuifje-missie voorstellen om het concrete gat gericht te onderzoeken;
- onderscheid maken tussen feit, inferentie en interpretatie;
- een inhoudelijk coherent verhaal of bijgewerkt dossier maken;
- compacte rolling state schrijven met bronverwijzingen, tegenbewijs en open vragen;
- state als verliesgevende kenniskaart mogen consolideren: samenvatten,
  samenvoegen en herschrijven is toegestaan zolang het lossless bronarchief via
  stabiele refs beschikbaar blijft;
- via `recall_weekendkrant_part` eerder verwerkt materiaal gericht opnieuw
  opvragen wanneer een later spoor herlezing nodig maakt, in plaats van alle oude
  bronnen standaard opnieuw in context te laden;
- expliciete dossierkoppelingen en begrensde Kuifje-missies voorstellen;
- op verzoek de eigen state comprimeren met behoud van onzekerheden en provenance.

Leonardo krijgt zoveel redactionele vrijheid als nuttig is, maar mag feitelijke claims niet losmaken van het bronmateriaal.

Sherlock blijft breed scouten; Leonardo beoordeelt de inhoudelijke lacunes in
het samengestelde dossier of verhaal. Ariadne beoordeelt die lacunes nooit zelf;
zij valideert alleen de expliciete missie, koppelingen en technische budgetgrenzen.

De standaardkandidaat voor Leonardo is een middenmodel zoals Terra, om kwaliteit en kost in balans te houden.

## Einstein: geplande rol voor de tijdsdimensie

Einstein onderzoekt later persistente redactionele state in de tijd: wat doorheen
opeenvolgende observaties of states groeit of verzwakt, welke signalen terugkeren,
versnellen of uitdoven, wat van karakter verandert en welke oude signalen achteraf
betekenis krijgen. Langetermijnontwikkelingen en andere longitudinale patronen
zijn zijn primaire analytische verantwoordelijkheid.

Einstein is uitsluitend gepland: deze PR voegt geen `roles/einstein.md`, job,
producer/adapter, scheduler, schema of runtimecode toe. Ariadne verricht noch
Leonardo's structurele analyse, noch Einsteins temporele analyse; zij blijft de
deterministische opslag-, validatie-, budget- en routinglaag.

## Kuifje — de onderzoeksreporter (fase 12)

Kuifje werkt in één run aan de ordered 1..4 afgebakende onderzoeksmissies van
één succesvolle Leonardo-finish, binnen exact hetzelfde topic. Iedere missie
wordt afzonderlijk immutable gevalideerd en opgeslagen. Leonardo start of spawnt Kuifje dus niet rechtstreeks:
de 1..4 missies vormen samen één ready Kuifje-job die later via dezelfde
generieke dispatcher wordt geclaimd. Hij krijgt de vraag en relevante context, zoekt aanvullend bewijs of
tegenspraak en levert bronvaste resultaten onder dezelfde missie- en
dossieridentiteit. Ook lege oogst en beperkingen worden expliciet gerapporteerd.

Kuifje bepaalt niet zelf naar welk dossier zijn oogst gaat en vervangt Sherlocks
brede signalering niet. Ariadne routeert zijn resultaten zonder inhoudelijk oordeel.
Kuifje wijzigt de Leonardo-state niet zelf; een volgende Leonardo-iteratie verwerkt
nieuwe bronrevisies in een volgende state; missies blijven aparte runtime-state.
Zie het [actuele fase-12-contract](phase-12-kuifje.md) en de frozen
[rolinstructie](../roles/kuifje.md).
Zie het [missie- en geheugenontwerp](leonardo-memory-and-orchestration.md).

## Striktland — de feitencontroleur

Striktland krijgt Leonardo's tekst en precies de relevante bronfragmenten.

### Verantwoordelijkheden

Per feitelijke claim bepalen of die:

- `VERIFIED` is;
- `PARTIALLY_SUPPORTED` is;
- een `INFERENCE` is;
- `UNSUPPORTED` is;
- of door een bron wordt `CONTRADICTED`.

Striktland schrijft geen nieuw verhaal en gaat niet zelfstandig op onderzoek. Zijn taak is smal: nagaan of een claim daadwerkelijk gedragen wordt door het aangeleverde bewijs.

Een goedkoop model zoals Luna is hiervoor de voorkeurskandidaat.

## Minos — het eindoordeel

Minos wordt alleen ingeschakeld wanneer Striktland een relevante fout vindt.

### Verantwoordelijkheden

- uitsluitend de problematische passage ontvangen;
- relevante bronfragmenten ontvangen;
- de passage corrigeren of herschrijven;
- daarna stoppen.

Minos wordt niet opnieuw door Striktland gecontroleerd. Het systeem accepteert daar bewust een restrisico om regressielussen te vermijden.

Voor Minos wordt het krachtigste model, bijvoorbeeld Sol, alleen uitzonderlijk gebruikt.

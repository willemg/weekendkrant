# Rollen

## Sherlock — de speurneus

Sherlock is een actieve ChatGPT-taak.

Sherlock levert fiches via de Weekendkrant Ingress MCP-plugin aan de HTTPS-API.
SQLite bewaart de transportqueue; GitHub is geen transportqueue. Het dagelijkse
consumentencontract heeft exact `schema_version: 1`, `topic: 1|2|3`, een Belgische
ISO-kalenderdatum en niet-lege Markdown in `content`. De oude Git-header en
`closed`-melding worden niet meer gebruikt. Sherlock voert zijn dagelijkse run
vóór Ariadne uit; deze PR wijzigt zijn actieve taak niet.

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
het Git-afsluitcontract is niet meer operationeel. Deze PR past Sherlocks actieve
taak niet aan.

### Onderzoeksgebieden

De inhoudelijke scope hieronder is het **zoekterrein**, niet een verplicht uitvoerschema. Sherlock hoeft niet in één run alle hieronder beschreven redactionele taken perfect uit te voeren. De bestaande vijf actieve nieuwstaken vormen voorlopig vooral onze bron voor welke onderwerpen en signalen interessant zijn.

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

Geïmplementeerd zijn de SQLite-backlogconsument en de
[dagelijkse deterministische verwerking](daily-runtime.md).

### Verantwoordelijkheden

- pending fiches tot en met vandaag in Europe/Brussels in één snapshot verwerken;
- oude pending fiches automatisch meenemen zonder afzonderlijke herstelmodus;
- dagelijks om 10:00 zonder polling starten; nul fiches is succes;
- queue-items na geslaagde output en provenance atomisch processed markeren;
- nieuwe Sherlock-output herkennen;
- fichetopic valideren tegen de vaste catalogus `1`, `2`, `3`;
- mechanisch groeperen per onderwerp;
- tokenaantal meten met `tiktoken==0.12.0`, encoding `cl100k_base`;
- lokale draden maken;
- maximaal 30.000 geserialiseerde brontokens per draad bewaken, met 5.000 reserve
  voor overige Leonardo-input; de toekomstige callbouwer moet de volledige
  request opnieuw meten en maximaal 35.000 inputtokens afdwingen;
- verwerkingsstatus en provenance in een lokale SQLite-database administreren;
- mislukte pogingen zichtbaar bewaren terwijl queue-items pending blijven;
- alle runtime-informatie via de centrale Python-`logging`configuratie schrijven,
  met levels en rotatie naar `/home/weekendkrant/logs/`.

Tijdens de observatiefase zijn Ariadnes draden afgeleide werkproducten. Ze hoeven niet
terug naar GitHub en moeten uit dezelfde ingress reproduceerbaar opnieuw opgebouwd
kunnen worden.
`daily` gebruikt een lokaal niet-blokkerend slot buiten de applicatierepository en
voert geen Git-operaties uit. De fiche-datum blijft provenance. Late arrivals
krijgen volgende legacy-parts op basis van succesvolle SQLite-provenance, zonder
eerdere output te herschrijven. Er is geen dagafsluit-gating, zondagjob,
weekrapport of automatische retentie. Bestaande data blijft behouden.

### Gepland geheugen- en budgetbeheer

Volgens het [doelontwerp van 8 oktober 2026](leonardo-memory-and-orchestration.md)
wordt Ariadne ook beheerder van Leonardo's persistente state en contextaanbieding:
state letterlijk opslaan en versioneren, omvang meten, nog niet aangeboden parts
over daggrenzen vullen, budget reserveren en werkelijk gebruik afrekenen.
Kuifje-resultaten volgen expliciete missie- en dossieridentifiers. Dit is nog
niet geïmplementeerd. Leonardo beslist over betekenis, compressie en inhoudelijke
verbanden; Ariadne controleert formaat, omvang, koppelingen en toegestane acties.

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

Leonardo krijgt een begrensde context met nieuwe bronparts, de geldige compacte
dossierstate en eventueel de oorspronkelijke Kuifje-missie met resultaten.
Elke call wordt expliciet samengesteld; continuïteit zit in de opgeslagen state
en bronnen. Dit is doelontwerp, geen bestaande modelruntime.

### Verantwoordelijkheden

- verbanden leggen;
- gebeurtenissen in context plaatsen;
- patronen herkennen;
- tegenstrijdigheden zichtbaar maken;
- onderscheid maken tussen feit, inferentie en interpretatie;
- een inhoudelijk coherent verhaal of bijgewerkt dossier maken;
- compacte rolling state schrijven met bronverwijzingen, tegenbewijs en open vragen;
- expliciete dossierkoppelingen en begrensde Kuifje-missies voorstellen;
- op verzoek de eigen state comprimeren met behoud van onzekerheden en provenance.

Leonardo krijgt zoveel redactionele vrijheid als nuttig is, maar mag feitelijke claims niet losmaken van het bronmateriaal.

De standaardkandidaat voor Leonardo is een middenmodel zoals Terra, om kwaliteit en kost in balans te houden.

## Kuifje — de onderzoeksreporter (gepland)

Kuifje werkt alleen aan een afgebakende onderzoeksmissie van Leonardo die Ariadne
binnen toegestane acties en budget kan uitvoeren. Hij krijgt de vraag en relevante
context, zoekt aanvullend bewijs of tegenspraak en levert bronvaste resultaten
onder dezelfde missie- en dossieridentiteit. Ook lege oogst en beperkingen worden
expliciet gerapporteerd.

Kuifje bepaalt niet zelf naar welk dossier zijn oogst gaat en vervangt Sherlocks
brede signalering niet. Ariadne routeert zijn resultaten zonder inhoudelijk oordeel.
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

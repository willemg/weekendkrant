# Rollen

## Sherlock — de speurneus

Sherlock is een actieve ChatGPT-taak.

Sherlocks inhoudelijke fiche-indeling blijft observerend; de technische header en
dagafsluiting liggen vast in het [versie-1-contract](daily-runtime.md). De eerste fase van het project is bewust observerend: gedurende enkele weken laten we Sherlock verzamelen en bekijken we wat een actieve taak in de praktijk betrouwbaar kan afleveren, hoeveel materiaal dat oplevert, hoe consequent de bronverwijzingen en samenvattingen zijn en hoeveel structuur zonder extra complexiteit haalbaar blijkt.

Pas op basis van die echte oogst leggen we het definitieve invoercontract voor Ariadne en de rest van de keten vast.

### Voorlopige verantwoordelijkheden

- periodiek het web afzoeken naar nieuwe ontwikkelingen;
- werken over een vaste maar uitbreidbare lijst interessegebieden;
- een eerste lichte triage proberen uit te voeren;
- per relevante vondst de oorspronkelijke bron bewaren;
- waar haalbaar de bron compact en feitelijk samenvatten;
- waar haalbaar een eenvoudige onderwerpindeling bewaren;
- de oogst naar GitHub schrijven;
- als laatste een expliciete gereedmelding voor de lokale datum publiceren,
  uitsluitend nadat alle dagoogst succesvol is gepusht; ook een lege oogst afsluiten;
- na die gereedmelding voor de afgesloten datum niets meer toevoegen;
- voor datum, ISO-week, ingressbranch en ingressmap uitsluitend de kalenderzone
  `Europe/Brussels` gebruiken; UTC of een impliciete omgevingstijdzone bepaalt nooit
  welke week actief is.

Deze lijst beschrijft de gewenste richting, niet een reeds bewezen betrouwbaar protocol.
De gereedmelding heeft een [concreet versie-1-contract](daily-runtime.md).
De [exacte instructieaanvulling](sherlock-dagafsluiting.md) moet nog handmatig in
Sherlocks actieve taak worden opgenomen. Zie
[dagafsluiting en dagelijkse uitvoering](architecture.md#dagafsluiting-en-dagelijkse-uitvoering-afgesproken-ontwerp).

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

Geïmplementeerd zijn de wekelijkse weekvoorbereiding en de
[dagelijkse deterministische verwerking](daily-runtime.md).

### Verantwoordelijkheden

- de wekelijkse Sherlock-werkruimte voorbereiden vóór Sherlock die nodig heeft;
- repository synchroniseren;
- dagelijks vanaf 10:00 Belgische tijd maximaal drie uur zelf pollen op Sherlocks
  gereedmelding, met tien minuten slaap tussen controles;
- de dagoogst uitsluitend na die gereedmelding verwerken;
- nieuwe Sherlock-output herkennen;
- fichetopic valideren tegen de vaste catalogus `1`, `2`, `3`, `4`;
- mechanisch groeperen per onderwerp;
- tokenaantal meten met `tiktoken==0.12.0`, encoding `cl100k_base`;
- lokale draden maken;
- garanderen dat de volledige input voor Leonardo nooit groter wordt dan 35.000 tokens;
- verwerkingsstatus en provenance in een lokale SQLite-database administreren;
- dagfouten voor de weekjob leesbaar bewaren, zonder de voorbereiding van de volgende
  week door een onvolledige oogst te blokkeren;
- alle runtime-informatie via de centrale Python-`logging`configuratie schrijven,
  met levels en rotatie naar `/home/weekendkrant/logs/`.

Tijdens de observatiefase zijn Ariadnes draden afgeleide werkproducten. Ze hoeven niet
terug naar GitHub en moeten uit dezelfde ingress reproduceerbaar opnieuw opgebouwd
kunnen worden.
Dagelijkse verwerking en weekvoorbereiding delen een slot en starten steeds uit
`app` op `main`; één aparte beheerde weekworktree bevat de ingressbranch.
Er zijn maximaal twee geregistreerde worktrees. De wekelijkse SQLite-retentie
bewaart de aflopende Belgische ISO-week plus de zeven voorgaande weken. Na een weekovergang haalt Ariadne geen oude weken in; late aanvullingen
blijven op de oude branch staan.

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

Leonardo krijgt één afgebakende draad plus eventueel een compacte bestaande dossierstate.

### Verantwoordelijkheden

- verbanden leggen;
- gebeurtenissen in context plaatsen;
- patronen herkennen;
- tegenstrijdigheden zichtbaar maken;
- onderscheid maken tussen feit, inferentie en interpretatie;
- een inhoudelijk coherent verhaal of bijgewerkt dossier maken.

Leonardo krijgt zoveel redactionele vrijheid als nuttig is, maar mag feitelijke claims niet losmaken van het bronmateriaal.

De standaardkandidaat voor Leonardo is een middenmodel zoals Terra, om kwaliteit en kost in balans te houden.

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

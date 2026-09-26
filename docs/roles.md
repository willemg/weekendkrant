# Rollen

## Sherlock — de speurneus

Sherlock is een actieve ChatGPT-taak.

### Verantwoordelijkheden

- periodiek het web afzoeken naar nieuwe ontwikkelingen;
- werken over een vaste maar uitbreidbare lijst interessegebieden;
- een eerste lichte triage uitvoeren;
- per relevante vondst de bron bewaren;
- de bron compact en feitelijk samenvatten;
- de vondst aan een vooraf bepaald onderwerp koppelen;
- output naar GitHub schrijven.

### Onderzoeksgebieden

Sherlocks onderzoeksbrief neemt de inhoudelijke scope over die vandaag verspreid zit over de vijf actieve nieuwstaken. Hij zoekt niet alleen naar losse gebeurtenissen, maar vooral naar ontwikkelingen die structureel iets kunnen veranderen.

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

Sherlock hoeft daar nog geen eindinterpretatie van te maken. Hij moet zulke mogelijke verbindingen alleen zichtbaar genoeg bewaren zodat Leonardo ze later kan onderzoeken.

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

De output moet daarom vooral bestaan uit compacte, afzonderlijke bronfiches.

## Ariadne — de draadlegger

Ariadne is geen agent maar een deterministisch script, waarschijnlijk gestart via cron op een Raspberry Pi.

### Verantwoordelijkheden

- repository synchroniseren;
- nieuwe Sherlock-output herkennen;
- mechanisch groeperen per onderwerp;
- tokenaantal meten met bijvoorbeeld `tiktoken`;
- draden maken;
- garanderen dat de volledige input voor Leonardo nooit groter wordt dan 35.000 tokens;
- verwerkingsstatus administreren.

### Niet doen

Ariadne mag niet:

- samenvatten;
- relevantie beoordelen;
- semantisch dedupliceren;
- verbanden leggen;
- bronnen interpreteren.

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

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

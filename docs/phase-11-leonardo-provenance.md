# Fase 11: fijnmazige Leonardo-provenance

Fase 11 verrijkt Leonardo's compacte redactionele state met fijnmaziger
bronprovenance. Deze fase volgt na fase 10, die voor het rudimentaire CI-systeem
is gereserveerd.

Deze pagina legt uitsluitend het ontwerp en de implementatiegrenzen vast. De
documentatie-PR voor fase 11 wijzigt geen runtimecontract, schema, validator,
scheduled taak, plugin of productiegedrag.

## Aanleiding

De fase-9.6-karakterisering liet Leonardo grote hoeveelheden nieuwe broncontext
succesvol structureren. Daarbij signaleerde Leonardo zelf in zowel de
wetenschaps- als AI-state een beperking: individuele state-items konden alleen
naar volledige `part:<id>:<revision>`-revisies verwijzen, terwijl één part veel
afzonderlijke fiches bevat.

Dat is geen verlies van bronprovenance in Ariadne. De immutable parttekst bevat
per fiche een `SOURCE queue:<id>`-identiteit en SQLite bewaart de exacte
revision-membership naar `queue_id`, bronbytes, hash, datum en positie. De
beperking ontstaat in het huidige Leonardo-outputcontract en de statevalidator:
item-level `refs`, `support` en `counterevidence` mogen alleen waarden uit
`processed_refs` gebruiken, en `processed_refs` bevat partrevisies.

De vroege ontwikkelfase is niet het moment om deze beschikbare granulariteit
voortijdig weg te abstraheren. We weten nog niet welke redactionele,
audit-, Striktland-, Kuifje- of latere krantworkflows fijnmazige bronidentiteit
nodig zullen hebben.

## Ontwerpprincipe

Bewaar zoveel mogelijk bronidentiteit zolang de kosten en grenzen nog
karakteriseringsdata zijn. Leonardo mag inhoudelijk abstraheren, maar zijn
provenance mag fijner blijven dan zijn tekstuele synthese.

Meer granulariteit betekent niet dat ieder state-item verplicht elke
onderliggende fiche moet opsommen. Leonardo kiest de semantisch passende
granulariteit:

- een brede hypothese over een volledige bronbundel mag naar één of meer
  `part:<id>:<revision>`-refs verwijzen;
- een concrete claim die door specifieke fiches gedragen wordt, mag naar
  `queue:<id>`-refs verwijzen;
- een item mag beide vormen combineren wanneer een deel van het bewijs
  partbreed en een ander deel fiche-specifiek is.

De backend valideert identiteit en bereik, niet de inhoudelijke keuze voor een
grovere of fijnere verwijzing.

## Twee provenance-lagen in de state

### Verwerkingsprovenance

`processed_refs` blijft de compacte, exacte verzameling immutable partrevisies
die Leonardo heeft verwerkt. Dit veld beantwoordt:

> Welk broncorpus heeft deze state gezien?

Het wordt dus niet opgeblazen tot honderden queue-ID's. De bestaande invariant
blijft het uitgangspunt: eerdere processed partrefs blijven behouden en alle
nieuwe aangeboden partrevisies worden toegevoegd.

### Itemprovenance

De provenancevelden van afzonderlijke state-items krijgen een rijker domein:

- `hypotheses[].refs`
- `uncertainties[].refs`
- `open_questions[].refs`
- `claims[].support`
- `claims[].counterevidence`

Deze velden mogen in fase 11 verwijzen naar:

1. een verwerkte `part:<id>:<revision>`; of
2. een `queue:<id>` die aantoonbaar lid is van ten minste één verwerkte
   partrevisie.

Een willekeurige queue-ID buiten het immutable verwerkte corpus blijft ongeldig.
Topicgelijkheid, tekstgelijkenis of aanwezigheid elders in het archief geeft
geen autorisatie.

## Backendvalidatie

De toekomstige implementatie moet fijnmazige refs deterministisch kunnen
valideren zonder Leonardo te vertrouwen voor bronlidmaatschap.

Voor iedere `queue:<id>` in itemprovenance geldt conceptueel:

```text
queue:<id>
    -> revision_sources
    -> lid van minstens één part:<id>:<revision>
       uit processed_refs
```

De bestaande immutable revision-membership en `source_archive` blijven de
autoritatieve bron. Geen heuristische lookup op titel, URL, datum of inhoud.

Bestaande partrefs blijven geldig. Bestaande opgeslagen states worden niet
herschreven om kunstmatig fijnmaziger te lijken.

## Recall

Fase 11 vereist niet automatisch een nieuwe fiche-recalltool. Een part-recall
levert de exacte gereconstrueerde parttekst al met de individuele
`SOURCE queue:<id>`-grenzen. Leonardo kan daardoor tijdens een geldige job
fiche-identiteiten opnieuw waarnemen wanneer hij een part gericht herleest.

Een afzonderlijke fiche-recallroute is pas gerechtvaardigd als latere
karakterisering aantoont dat part-recall voor selectieve herlezing aantoonbaar
te grof of te duur is. Dat is geen voorwaarde voor fase 11.

## Stateomvang is voorlopig geen reden om granulariteit weg te gooien

De eerste grote karakteriseringsstates bleven veel kleiner dan hun broninput.
Fase 11 mag daarom niet uit voorzorg queue-provenance verwijderen om de huidige
compactheidsdoelen cosmetisch te behouden.

De bestaande stategrenzen zijn nog steeds technische contractgrenzen. Als
fijnmazige provenance in realistische productie-input tegen de 4.000-token- of
32-KiB-grens botst, moet de implementatiefase dat expliciet meten en vervolgens
een bewuste contractkeuze maken. Stil terugvallen naar grovere refs of
bronidentiteiten afkappen is niet toegestaan.

## Contract- en compatibiliteitsgrens

De runtimecontracten onder `roles/` worden door assignments exact ingevroren.
De implementatie van fase 11 moet daarom expliciet beslissen hoe het uitgebreid
refdomein wordt geversioneerd en gevalideerd zonder de betekenis van reeds
bevroren jobs stilzwijgend te veranderen.

Minimale compatibiliteitsvoorwaarden:

- bestaande part-only states blijven geldig;
- historische states worden niet gemigreerd alsof ze fijnmazige provenance
  bevatten;
- een oude immutable assignment blijft volgens zijn eigen contractsnapshot
  interpreteerbaar;
- nieuwe assignments krijgen een contract dat de toegestane part- en queue-refs
  letterlijk beschrijft;
- backendvalidatie en runtimecontract mogen niet van elkaar afwijken.

Of dit een compatibele verruiming van state schema v1 kan zijn of een expliciete
nieuwe outputcontractversie vereist, wordt in de implementatie-PR beslist met
tests tegen frozen oude assignments.

## Inspectie en karakterisering

De operatorinspectie moet na implementatie zichtbaar kunnen maken hoeveel
item-level provenance op part- en ficheniveau werd gebruikt. Minimaal interessant:

- aantal unieke partrefs in itemprovenance;
- aantal unieke queue-refs in itemprovenance;
- items zonder fijnmazige refs terwijl de tekst een concrete bronclaim doet;
- eventueel de herleiding `queue:<id>` naar partrevisie en Sherlock-run waar
  die metadata beschikbaar is.

Dit zijn karakteriseringssignalen, geen automatische inhoudelijke
kwaliteitsscore.

## Niet in fase 11

Fase 11 introduceert niet:

- semantische routing door Ariadne;
- automatische dossierkeuze;
- Einstein-longitudinale analyse;
- Kuifje-missies of worker-spawning;
- Striktland-validatie van de inhoudelijke claim zelf;
- een nieuwe scheduler;
- providerusage- of kostenmeting;
- retentie of verwijdering van bronmateriaal.

De stap verrijkt uitsluitend de traceerbaarheid van Leonardo's eigen
structurele output tot de fijnste reeds beschikbare bronidentiteit.

## Implementatiebewijs voor de latere functionele PR

De functionele fase-11-PR moet ten minste aantonen dat:

1. part-only output achterwaarts geldig blijft;
2. geldige `queue:<id>`-refs uit processed revisions worden geaccepteerd;
3. queue-refs buiten die revisions hard worden geweigerd;
4. gemengde part- en queue-provenance geldig is;
5. support en counterevidence onafhankelijk fijnmazig kunnen zijn;
6. retries, fencing en atomische statefinish dezelfde garanties behouden;
7. frozen oude assignments hun bestaande contractsemantiek behouden;
8. inspectie de nieuwe granulariteit reproduceerbaar zichtbaar maakt.

De concrete fast-track wordt pas in die functionele PR opnieuw beoordeeld.

# Weekproductie: doelmodel voor capaciteit, afhankelijkheden en afsluiting

Dit document beschrijft het **toekomstige weekritme** van Weekendkrant. Het is
een doelmodel voor latere capaciteits-, dispatcher- en weekafsluitingsfasen, geen
beschrijving van de huidige productieruntime.

De harde redactionele deadline is:

> **zondag 09:00 Europe/Brussels: de Weekendkrant is klaar.**

Dat moment is tegelijk de afsluiting van de vorige editie en het begin van de
volgende productieweek. De daaropvolgende 168 uurlijkse executoractivaties,
van zondag 09:00 tot en met zondag 08:00, vormen de maximale ruwe capaciteit
waarbinnen scouting, synthese, gericht onderzoek, verificatie en eindredactie
moeten worden afgewerkt.

De 168 slots zijn **capaciteit**, geen vooraf ingevulde agenda. Werk ontstaat uit
persistente state en afhankelijkheden; een rol krijgt pas een slot wanneer haar
input werkelijk klaarstaat. De weekplanning moet dus deadline-gedreven en
state-driven zijn, niet een statische tabel waarin elk uur vooraf aan één rol is
toegewezen.

## De week als 72 + 72 + 24 uur

Het doelmodel deelt de 168 uurslots op in drie vensters:

| Venster | Tijd | Slots | Primair doel |
| --- | --- | ---: | --- |
| Golf A | zondag 09:00 → woensdag 08:00 | 72 | eerste brede inhoudelijke cyclus voor alle drie topics |
| Golf B | woensdag 09:00 → zaterdag 08:00 | 72 | tweede brede inhoudelijke cyclus voor alle drie topics |
| Afsluiting | zaterdag 09:00 → zondag 08:00 | 24 | verificatie, correctie, longitudinale afsluiting en finale krant |

Samen:

```text
72 + 72 + 24 = 168 uur
```

Deze grenzen zijn redactionele deadlines, geen verplichting dat een bepaalde
job precies op een bepaald uur start. Topic 1 kan in een golf sneller door zijn
keten lopen dan topic 3. Ongebruikte capaciteit mag leeg blijven of door ander
ready werk worden benut.

## Twee volledige inhoudelijke golven per week

Voor elk van de drie vaste topics is het voorlopige doel twee zelfstandige
inhoudelijke golven per week. Iedere golf moet binnen haar driedaagse venster
kunnen worden afgesloten.

Per topic ziet het maximale normale pad er conceptueel zo uit:

```text
Sherlock
   |
   v
Leonardo 1
   |
   +--> geen relevante lacune --------------------+
   |                                              |
   +--> Kuifje-missie                             |
           |                                      |
           v                                      |
        Kuifje 1                                  |
           |                                      |
           v                                      |
        Leonardo 2                                |
           |                                      |
           +--> geen tweede missie ---------------+
           |
           +--> Kuifje-missie
                   |
                   v
                Kuifje 2
                   |
                   v
        afsluitende Leonardo-run
```

Dat zijn maximaal zes inhoudelijke runs per topic en per golf:

1. Sherlock zoekt breed binnen het topic;
2. Leonardo structureert de nieuwe oogst en bepaalt of een concrete lacune een
   gerichte Kuifje-missie rechtvaardigt;
3. Kuifje onderzoekt die missie alleen wanneer ze werkelijk bestaat;
4. Leonardo verwerkt het antwoord en bepaalt of nog één gerichte vervolgmissie
   nodig is;
5. een tweede Kuifje-run is opnieuw conditioneel;
6. Leonardo sluit de golf inhoudelijk af.

De Kuifje-stappen zijn dus **reservecapaciteit**, geen quotum. Geen lacune
betekent geen missie en geen run. Een vruchteloze missie is eveneens een geldig
resultaat en mag niet automatisch een nieuwe zoeklus veroorzaken.

Bij drie topics is het theoretische maximum per golf:

```text
3 topics × 6 runs = 18 inhoudelijke runs
```

Twee golven geven maximaal 36 runs voor deze basiscyclus. Het werk mag tussen
topics worden geïnterleaved; er is geen reden om eerst één volledig topic af te
werken voordat een ander topic vooruit kan.

## Waarom drie dagen per golf

De driedaagse grens heeft twee doelen.

Ten eerste voorkomt zij dat de eerste Sherlock-oogst de hele week blijft
doorschuiven. Een golf krijgt een echte eindgrens en moet tot een bruikbare
Leonardo-synthese komen.

Ten tweede laat zij ruimte voor **een tweede onafhankelijke observatiegolf**
binnen dezelfde krantweek. De tweede Sherlock-run hoeft daardoor niet alleen
meer materiaal aan een oude stapel toe te voegen, maar kan een nieuwe actuele
doorsnede van het topic leveren waarop Leonardo opnieuw structureel reageert.

De twee golven zijn inhoudelijk verbonden binnen dezelfde krantweek, maar de
tweede golf is geen verplicht herhalen van dezelfde onderzoeksvragen. Nieuwe
feiten kunnen eerdere hypotheses versterken, verzwakken, splitsen of irrelevant
maken.

## Leonardo begint iedere krantweek van een blanco blad

Leonardo maakt de Weekendkrant. Zijn redactionele week begint daarom bij de
weekgrens **zonder de vorige krant als doorlopende redactionele state**.

Binnen één productieweek mag Leonardo uiteraard voortbouwen op zijn eerdere
runs van diezelfde week:

```text
Sherlock A
 -> Leonardo A
 -> Kuifje
 -> Leonardo A-close
 -> Sherlock B
 -> Leonardo B
 -> ...
 -> Leonardo final
```

Maar bij de volgende zondagse weekgrens begint de nieuwe krant opnieuw als een
nieuwe redactionele constructie.

Dat betekent niet dat historisch bronmateriaal wordt verwijderd. De lossless
bronlaag, eerdere kranten, claims en states blijven beschikbaar voor audit en
voor rollen die tijdsverbanden onderzoeken. Het betekent alleen dat Leonardo
niet verantwoordelijk is voor longitudinale continuïteit tussen krantweken.

Die taak hoort bij Einstein.

## Einstein als longitudinale dwarsstroom

Einstein past niet netjes in de twee topicgolven. Zijn natuurlijke dimensie is
tijd: terugkeer, groei, verzwakking, versnelling, uitdoving en
karakterverandering van signalen over eerdere observaties en krantweken heen.

Daarom loopt Einstein als een **dwarsstroom door de week**:

```text
topicgolven:   S -> L -> K? -> L -> K? -> L
                S -> L -> K? -> L -> K? -> L

Einstein:         E -------- E -------- E -------- E?
                   \         \                   /
                    -> Kuifje? -> Einstein vervolg
```

De precieze Einstein-frequentie is nog niet gekozen en mag niet zonder meting
worden hardgecodeerd. Zijn runs moeten voldoende nieuwe temporele informatie
hebben om zinvol te zijn.

Een Einstein-run kan zelf een gerichte lacune vinden. Ook Einstein moet daarom
later een Kuifje-missie kunnen voorstellen, via hetzelfde duurzame
missie-/dispatcherpad als Leonardo:

```text
Einstein
   |
   v
longitudinale onderzoeksvraag
   |
   v
Kuifje
   |
   v
Einstein verwerkt resultaat
```

Het semantische verschil zit in de aanleiding:

- Leonardo vraagt aanvullend onderzoek om een **inhoudelijke of structurele
  lacune in de huidige week** te dichten;
- Einstein vraagt aanvullend onderzoek om een **longitudinale hypothese of
  verandering door de tijd** te toetsen.

Kuifje zelf blijft een generieke missieonderzoeker en hoeft daarvoor geen
aparte scheduler te krijgen.

## Einstein krijgt een eigen krantbijdrage

Einstein is niet gewoon een vierde Sherlock-topic. Zijn eindproduct hoort als
een afzonderlijke longitudinale rubriek in de Weekendkrant.

Die rubriek kan bijvoorbeeld zichtbaar maken:

- welk nieuws deze week nieuw lijkt maar in werkelijkheid al langer groeit;
- welke eerdere signalen sterker of structureler worden;
- welke verwachte patronen juist verzwakken of uitdoven;
- welke oude losse observaties pas nu samen betekenis krijgen;
- waar de ontwikkeling van karakter verandert in plaats van alleen groter of
  kleiner te worden.

De uiteindelijke naam en vorm van de rubriek blijven open. De architecturale
grens ligt wel vast: Einstein levert tijdsstructuur, niet een vierde brede
nieuwsoogst.

## De laatste 24 uur: van onderzoek naar publicatie

Vanaf zaterdag 09:00 verandert de doelstelling van de dispatcher.

Tijdens Golf A en Golf B is de centrale vraag:

> Welke nuttige informatie of synthese moet nog ontstaan?

Tijdens de laatste 24 uur wordt dat:

> Welke open ketens moeten nog gesloten worden om zondag om 09:00 een
> betrouwbare krant te kunnen publiceren?

Nieuwe brede scouting krijgt dan steeds minder waarde. De resterende capaciteit
moet beschikbaar zijn voor verificatie, correctie en finale synthese.

Een voorlopig afsluitpad is:

```text
inhoudelijke weekstate
        |
        v
Leonardo maakt/selecteert concrete krantclaims en passages
        |
        v
Striktland verifieert claims tegen primaire bronprovenance
        |
        +--> goed -----------------------------+
        |                                      |
        +--> relevant probleem                 |
                 |                             |
                 v                             |
               Minos                           |
                 |                             |
                 +-----------------------------+
                               |
                               v
                    finale Leonardo-run
                               |
                               v
                     Weekendkrant klaar
                     zondag 09:00
```

Striktland hoeft niet exact één run per topic te krijgen. Zijn natuurlijke
werkeenheid kan later een begrensde set claims, passages of bewijsbundels zijn.
Een topic met veel risicovolle claims kan meer verificatiecapaciteit vereisen
dan een topic met weinig controversiële beweringen.

Minos is volledig conditioneel. Capaciteit voor Minos moet beschikbaar zijn,
maar een goede week kan eindigen zonder enige Minos-run.

Na Striktland en eventuele Minos-correcties krijgt Leonardo de finale
redactionele verantwoordelijkheid: hij verwerkt de controles en correcties en
zet de laatste inhoudelijke stempel op de editie.

## Finale Leonardo is geen nieuwe onderzoeksronde

De finale Leonardo-run is een afsluitende redactionele stap. Hij mag geen
onbegrensde nieuwe onderzoekscyclus openen die de publicatiedeadline voorbij
duwt.

Als vlak voor publicatie een ernstige onbeantwoorde onzekerheid overblijft,
moet het systeem liever:

- de claim schrappen;
- de onzekerheid zichtbaar maken;
- of het verhaal uitstellen;

dan op het laatste moment een onbeperkte Sherlock/Kuifje-lus te starten.

Deadlinebeleid moet dus niet alleen bepalen welk werk voorrang krijgt, maar ook
welk nieuw werk **niet meer toegelaten** wordt.

## Van klokplanning naar een deadline-gedreven DAG

De hierboven beschreven volgorde is het best te modelleren als een directed
acyclic graph van afhankelijkheden.

Een slot wordt niet toegewezen omdat het bijvoorbeeld "maandag 14:00
Leonardo-uur" is. Een Leonardo-job wordt ready omdat zijn vereiste Sherlock- of
Kuifje-input duurzaam aanwezig is.

Conceptueel:

```text
tijd levert capaciteit
state levert ready work
deadlines bepalen prioriteit
```

Dat sluit aan bij de generieke dispatcherarchitectuur. De scheduler hoeft geen
inhoudelijke beslissingen te nemen en een modelworker start nooit rechtstreeks
een andere worker. Een rol kan een duurzaam voorstel produceren; backend/state
maakt daar later een ready job van.

## Urgentie neemt toe richting de deadline

Niet ieder ongebruikt uur is even kostbaar.

Een leeg slot op zondagmiddag kan zonder gevolg blijven. Een mislukte
Striktland-run op zondagochtend kan publicatie blokkeren.

Het latere capaciteitsbeleid moet daarom naast gewone rolprioriteit ook
**deadline-urgentie** kunnen modelleren.

Een mogelijk principe:

```text
vroeg in de week:
    nieuwe informatie is waardevol

midden van de week:
    nieuwe informatie + open onderzoeksketens afwerken

laat in de week:
    open ketens sluiten > nieuw breed werk starten

vlak voor publicatie:
    verificatie/correctie/finale synthese
    > nieuw onderzoek
```

De concrete thresholds zijn nog niet beslist en moeten op echte looptijden,
failure rates, platformallowance en kwaliteitsmetingen gebaseerd worden.

## Ruwe capaciteitsrekening

De 168 beschikbare uuractivaties zijn geen belofte dat 168 modelruns betaalbaar
of nuttig zijn. Ze geven alleen een bovengrens aan de schedulerfrequentie.

Voor de basis van drie topics:

```text
2 golven
× 3 topics
× maximaal 6 inhoudelijke runs
= maximaal 36 runs
```

Een conservatieve afsluiting met bijvoorbeeld maximaal één Striktland, één
Minos en één finale Leonardo-stap per topic zou daar hoogstens negen
topicgebonden runs aan toevoegen:

```text
36 + 9 = 45
```

Dit is uitsluitend een **capaciteitsillustratie**, geen gewenste runquota.
Kuifje en Minos zijn conditioneel, Striktland kan een andere granulariteit
krijgen en Einstein plus Einstein-Kuifje-ketens komen daar nog bovenop.

Het belangrijkste gevolg is daarom niet dat 168 slots mathematisch meteen
opgebruikt zijn. Het probleem is dat afhankelijkheden, variabele looptijden,
platformbudget en de naderende deadline de werkelijk bruikbare capaciteit veel
schaarser maken dan het ruwe aantal suggereert.

## Reservecapaciteit is onderdeel van de planning

Een systeem dat alle 168 slots vooraf vult, heeft geen ruimte meer voor
onverwachte maar belangrijke vervolgvragen, failures of correcties.

Daarom moet het latere weekbeleid expliciet capaciteit kunnen vrijhouden voor:

- Kuifje-missies die pas uit Leonardo- of Einstein-analyse ontstaan;
- retries na echte technische failure;
- Striktland-verificatie;
- Minos-correctie;
- finale Leonardo;
- mogelijk een laatste Einstein-verwerking voor zijn longitudinale rubriek.

"Geen werk" in een slot is dus niet automatisch inefficiëntie. Vrije capaciteit
kan een bewuste veiligheidsmarge zijn.

## Weekgrenzen en laat binnenkomend materiaal

De publicatiedeadline bepaalt de editiegrens. Laat materiaal vlak voor zondag
09:00 mag de krant niet stilzwijgend onbegrensd openhouden.

De latere implementatie moet expliciet bepalen:

- wanneer nieuwe Sherlock-oogst niet meer voor de lopende editie wordt
  toegelaten;
- wanneer een late maar kritieke bron nog een bestaande claim mag wijzigen;
- welke onafgeronde missie doorschuift naar een volgende onderzoekscontext;
- hoe de nieuwe krantweek vanaf zondag 09:00 met een blanco Leonardo-redactie
  start zonder historisch bronbewijs te verliezen.

Deze regels zijn nog niet geïmplementeerd.

## Relatie met toekomstige fasen

Dit weekmodel is vooral input voor:

- **fase 12, Kuifje:** duurzame conditionele onderzoeksmissies;
- **fase 13, Striktland:** claimverificatie tegen bronprovenance;
- **fase 14, Minos:** begrensde correctie op geregistreerde problemen;
- **fase 15, capaciteits- en budgetbeleid:** slots, prioriteit, reserves,
  allowance en deadline-urgentie;
- **fase 16, weekafsluiting/eindredactie:** freeze/admissionbeleid,
  verificatievolgorde en finale publicatie.

Einstein heeft nog geen eigen implementatiefase in de huidige roadmap. Zijn
longitudinale rol en plaats in deze weekcyclus moeten vóór implementatie nog in
een afzonderlijk contract worden uitgewerkt.

## Niet vastgelegd door dit document

Dit document kiest bewust nog niet:

- een exacte Einstein-frequentie;
- vaste klokuren per rol;
- hoeveel parallelle executors uiteindelijk nodig zijn;
- provider- of weekbudget per rol;
- het exacte aantal Striktland-jobs;
- een verplicht aantal Kuifje- of Minos-runs;
- definitieve deadline-thresholds voor admission;
- de technische krantstate-/draftschemas;
- de definitieve publicatieadapter.

Die keuzes moeten later uit echte runtimegegevens, inhoudelijke kwaliteit en
beschikbaar platformbudget volgen.

De blijvende ontwerpintentie is wel duidelijk:

> **zondag 09:00 is de deadline; de week ervoor is een state-driven,
> deadline-gedreven redactionele productieketen die brede scouting vroeg laat
> gebeuren en richting publicatie steeds meer capaciteit reserveert voor
> verificatie, correctie en finale synthese.**

# Leonardo: geheugen, draden en deterministische regie

## Status en besluit van 8 oktober 2026

Dit document legt het doelontwerp vast. Het implementeert geen modelcalls,
weekoverschrijdende dossiers, Kuifje-missies of nieuw databaseschema.

De huidige `daily` verwerkt één dagsnapshot. `weave()` bundelt alleen de
aangeboden fiches; `run_daily()` levert uitsluitend de oogst van vandaag en
schrijft `YYYY-MM-DD_PPPP.txt`. De deelnummering begint per topic en dag opnieuw.
Een kleine draad van gisteren wordt vandaag dus niet verder gevuld. Ook
`threads` en `sources` zijn in SQLite aan een dag gekoppeld. Dit is het
[huidige runtimecontract](daily-runtime.md), niet het gewenste eindontwerp.

Het nieuwe uitgangspunt is:

> Leonardo beheert de betekenis van zijn geheugen; Ariadne beheert de opslag,
> omvang, aanbieding en kosten ervan.

Ariadne blijft volledig deterministische lokale software. Ze gebruikt geen LLM
om fiches te ordenen, state samen te vatten of onderzoeksvragen te kiezen.

## Verantwoordelijkheden

| Rol | Beslist of doet |
| --- | --- |
| Sherlock | Vindt signalen en levert bronvaste fiches met expliciet topic. |
| Ariadne | Valideert metadata, bewaart bronnen en state, telt tokens, bundelt deterministisch, bewaakt budgetten en voert toegestane acties uit. |
| Leonardo | Herkent patronen, kiest inhoudelijke dossierverbanden, schrijft rolling state en formuleert gerichte onderzoeksmissies. |
| Kuifje | Onderzoekt een afgebakende missie en retourneert bronnen, bevindingen, onzekerheden en eventuele lege oogst onder de meegegeven identifiers. |
| Striktland | Controleert claims tegen oorspronkelijke bronfragmenten. |
| Minos | Herschrijft waar nodig één keer de problematische passage. |

Kuifje is een toekomstige onderzoeksrol. Sherlock blijft de brede reporter:
dit ontwerp schuift geen missieadministratie of extra synthese naar hem door.

## Drie soorten context

Een vervolgcall kan alleen werken met informatie die opnieuw beschikbaar wordt
gemaakt in de request of via expliciet opgehaalde bronnen. Een lokale agent
hoeft daarom geen dagenlang open modelproces of contextwindow te hebben.

| Laag | Inhoud | Beheer |
| --- | --- | --- |
| Modelcontext | De concrete instructies, state, missies en bronnen van één call. | Ariadne stelt de request samen; het model verwerkt die. |
| Rolling dossierstate | Compacte hypotheses, claims, onzekerheden, open vragen en verwijzingen naar eerder verwerkt materiaal. | Leonardo schrijft de betekenis; Ariadne bewaart en versieert de bytes. |
| Bronarchief | De oorspronkelijke fiches, missies en exacte aangeboden partversies. | Lokale persistente opslag met stabiele identifiers en hashes. |

De identiteit van Leonardo zit in de combinatie van model, vaste instructies,
persistente state en het protocol dat vervolgcalls samenstelt. Een eventueel
providermechanisme voor conversaties of caching vervangt onze lokale audit niet.

Rolling state is verliesgevende compressie. Een eigen samenvatting wordt geen
nieuwe primaire bron en mag bij herhaling niet vanzelf aan bewijskracht winnen.
Originele fiches blijven beschikbaar voor gerichte herlezing en verificatie.

## Dag, topic, dossier en part

Deze begrippen hebben verschillende grenzen:

| Eenheid | Betekenis | Grens |
| --- | --- | --- |
| Dagelijkse consumptie | De deterministische selectie en verwerking van queue-items. | Lokale kalenderdag in Europe/Brussels. |
| Topic | Vooraf vastgelegde brede rubriek, momenteel 1, 2 of 3. | Expliciete fichemetadata. |
| Logisch dossier of draad | Een inhoudelijk onderzoek met eigen state en eventueel missies. | Expliciete redactionele beslissing van Leonardo. |
| Part | Een begrensde hoeveelheid broncontext voor een Leonardo-call. | Tokenbudget of expliciet aanbiedmoment. |

De huidige code noemt een fysiek inputbestand `thread`. Dat is nog geen
langlevend inhoudelijk dossier. Een topic is evenmin automatisch één coherent
verhaal: Leonardo kan in dezelfde topicbundel meerdere onafhankelijke sporen
vinden.

Voor de eerstvolgende verbetering bundelt Ariadne nieuwe Sherlock-fiches
**over daggrenzen heen, per week en topic**, in de laatste nog niet aangeboden
part. De technische identiteit wordt week + topic + part; de aanmaakdatum mag
zichtbaar blijven, maar sluit de part niet af. Verschillende topics worden
niet samengevoegd om het budget vol te krijgen.

Ariadne voegt in een vastgelegde deterministische volgorde hele fiches toe.
Past de volgende fiche niet, dan sluit ze de part en begint een volgende.
Ze zoekt geen combinatie die de resterende ruimte optimaal vult en beoordeelt
geen semantische verwantschap. De huidige lexicografische queuevolgorde is
geen chronologische volgorde; een nieuwe sorteersleutel moet bij implementatie
expliciet worden gekozen, gedocumenteerd en getest.

Een kleine part is toegestaan. Er wordt niet gewacht op precies 30.000 tokens
als een publicatiedeadline of toegestaan onderzoeksmoment aanbieding vereist.
De concrete aanbiedplanning is nog te bepalen.

Een logisch dossier kan later meerdere parts en weken omvatten. Na inhoudelijke
indeling door Leonardo volgt Ariadne alleen expliciete dossier- en bronkoppelingen.
Ze leidt die koppelingen niet af uit titels, tekst of gelijke topicnummers.

## Levenscyclus van een part

Een nog niet aangeboden part mag verder groeien. Zodra een concrete versie
aan Leonardo wordt aangeboden, ligt die versie vast. Audit registreert de
partidentiteit, revisie, bronvolgorde, exacte inhoudshash en tokenmeting.

Nieuwe fiches gaan daarna naar een volgende part of een expliciet gekoppelde
dossieraanvulling. Eerder aangeboden bytes worden niet stilzwijgend veranderd.
Ook een vervolgcall die opnieuw dezelfde bronnen nodig heeft verwijst naar
de werkelijk gebruikte versies.

Voor groeiende parts is het huidige bestand-eerst/DB-daarna-protocol niet
zonder meer voldoende. Een bestaande succesvolle part overschrijven vóór
DB-commit kan de eerder geregistreerde hash ongeldig maken als de commit faalt.
De implementatie moet daarom bestaande geregistreerde versies behouden,
bijvoorbeeld via nieuwe revisiebestanden en een korte transactionele update
van de actieve verwijzing. Losse niet-geregistreerde revisies zijn geen
gepubliceerde output.

Provenance moet kunnen aangeven welke fiches van verschillende dagen in
welke partrevisie zitten. Dagstatus en consumptie-identiteit blijven afzonderlijk
van dossier- en partidentiteit. Hiervoor zijn een schema- en migratieontwerp
nodig; dit document kiest nog geen definitieve tabelnamen of bestandslayout.

## Rolling state als contract

Leonardo levert na een tussenstap een compacte state volgens een te valideren
schema, met ten minste:

- dossieridentiteit en verwijzing naar de voorgaande stateversie;
- actuele hypotheses en expliciet onderscheiden bronfeiten en inferenties;
- claimidentifiers met ondersteuning én tegenbewijs via bronverwijzingen;
- onzekerheden, beperkingen en nog onbeantwoorde vragen;
- verwerkte partversies en onderzocht materiaal;
- open, afgeronde of vruchteloze onderzoekssporen;
- lopende missies en de reden waarom aanvullend bewijs nodig is.

Een streefomvang van ongeveer 1–2K tokens en een configureerbaar maximum rond
4K zijn ontwerpwaarden. De definitieve grenzen volgen uit het gekozen model,
prompt, kostenmetingen en kwaliteitsproeven; ze zijn nog geen runtimeconfiguratie.

Ariadne bewaart de state letterlijk, valideert vorm en identifiers, telt tokens
en versieert met hash. Ze controleert niet zelfstandig de inhoudelijke juistheid.
Ze kapt een te lange state nooit blind af.

Bij overschrijding blijft de vorige geldige state behouden. Een eventueel
compressieverzoek aan Leonardo krijgt zelf een begrensde input, output,
kostenreservering en maximaal aantal pogingen. Er komt geen onbeperkte
compressielus. Als geen geldige state ontstaat, stopt die verwerking zichtbaar
en blijven volgende parts ongelezen. De concrete fout- en herstelovergangen
moeten nog worden vastgelegd.

## Kuifje keert terug naar hetzelfde dossier

Leonardo formuleert een missie omdat in een dossier een concrete vraag openstaat.
Ariadne voert die alleen uit binnen vooraf toegestane acties en beschikbaar
budget. Een aanvraag is nog geen uitgevoerde missie.

Een missie bevat minimaal een stabiele `mission_id`, `parent_thread_id`
(de logische dossieridentiteit), `topic`, oorspronkelijke vraag, relevante
bron- of stateverwijzingen en een begrensd uitvoeringsbudget. Kuifje krijgt
alleen de context die voor die opdracht nodig is.

Zijn antwoord draagt dezelfde missie- en dossieridentiteit. Ariadne valideert
die tegen de opgeslagen opdracht en routeert mechanisch terug. Een onbekende
of tegenstrijdige koppeling wordt niet geraden. Ook niets gevonden, een fout
en onvolledig onderzoek zijn expliciete resultaten; ze bewijzen geen afwezigheid
van het onderzochte verschijnsel.

Een voorbeeld:

1. Leonardo krijgt part 1 met Sherlock-fiches A, B en C.
2. Hij levert state versie 3 en vraagt missie 12 naar onafhankelijke reproductie.
3. Ariadne bewaart beide en laat Kuifje binnen het toegestane budget werken.
4. Kuifje retourneert D en E onder missie 12 en hetzelfde dossier.
5. De vervolgcall krijgt state versie 3, de oorspronkelijke missie en D en E.
6. Leonardo levert state versie 4, inclusief wat de nieuwe bronnen veranderen.

A, B en C hoeven daarbij niet standaard opnieuw mee. Als de state onvoldoende
is, vraagt Leonardo gericht oorspronkelijke fiches op; die herlezing telt mee
in het volgende budget. Missie en resultaten blijven traceerbaar naar de
stateversie en partversies die aanleiding gaven tot het onderzoek.

De huidige schema-versie 1 accepteert exact vier fichevelden. Missievelden mogen
daar nu dus niet zomaar bij. Een uitbreiding vergt een expliciet geversioneerd
protocol en validatie in de volledige ingressketen.

## Context- en kostenbeheer door Ariadne

Ariadne stelt iedere call samen uit vaste instructies, de geldige dossierstate,
expliciete missiecontext, nieuwe bronparts en eventueel gevraagde herlezing.
De selectie volgt vaste volgorde en toegestane acties, niet Ariadnes oordeel
over relevantie.

Het projectbudget blijft **maximaal 35.000 inputtokens per Leonardo-call**.
De huidige bronpart heeft maximaal circa 30.000 geserialiseerde tokens met
5.000 reserve voor alle overige input samen. Die reserve is dus niet 5.000
extra tokens bóven de limiet en ook geen outputbudget.

Voor iedere werkelijke call geldt:

```text
input = instructies + berichtoverhead + state + missiecontext
        + nieuwe bronnen + expliciet opnieuw opgehaalde bronnen
input <= 35.000
input + gereserveerde output <= contextcapaciteit van gekozen model
```

Alle onderdelen worden samen gemeten met de tokenizer en berichtregels van
het gekozen model. De huidige `cl100k_base`-telling is een vastgelegde
bundelmeting, geen garantie voor ieder toekomstig model. Een part van 30K
past niet automatisch als state plus missies de overige 5K overschrijden.

Past een volgende hele fiche of part niet, dan wacht die op een volgende
call of wordt een nog niet aangeboden part deterministisch opnieuw verdeeld.
Een aangeboden versie blijft intact. Onvoldoende ruimte voor zelfs één fiche
geeft een expliciete budgetfout; inhoud wordt niet afgekapt.

Ariadne houdt per call de raming en werkelijke gebruikscijfers bij, inclusief
input, output en eventuele afzonderlijk gefactureerde redeneertokens,
cachegebruik en toolkosten volgens het providercontract. Tarieven en modelkeuze
worden geversioneerd; bedragen en week-/maandlimieten moeten nog worden gekozen.

Vóór uitvoering reserveert ze budget voor het begrensde maximale gebruik.
Na uitvoering rekent ze af met de werkelijke usage. Gelijktijdige aanvragen
mogen dezelfde resterende ruimte niet dubbel uitgeven. Retries,
compressie en Kuifje-missies vallen onder dezelfde boekhouding.
Bij een onzekere calluitkomst volgt geen blinde herhaling: eerst moet duidelijk
zijn of uitvoering en kosten al plaatsvonden.

## Wat slow burn hier betekent

Slow burn is onze strategie van begrensde progressieve verwerking:
nieuwe informatie plus compacte state, gevolgd door compacte tussenoutput.
De langere synthese volgt op een redactioneel gekozen moment.

De verwachte besparing komt van minder herlezen, minder irrelevante context
en minder herhaalde lange output. Kleine calls herhalen ook instructies en
state; extra compressiecalls kosten eveneens tokens. Daarom bundelen we waar
mogelijk hele fiches binnen het budget en laten we de kwaliteits- en
kostenmetingen het aanbiedritme bepalen.

35K is een projectgrens, geen bewezen economisch optimum. Trager aanbieden
of meer kleine calls is op zichzelf niet goedkoper. We leggen hier geen
actuele modeltarieven of gegarandeerde besparing vast. Zie de
[token- en kostenstrategie](token-and-cost-strategy.md).

## Opslag, audit en retentie

Iedere call moet herleidbaar zijn tot promptversie, model/configuratie,
input-stateversie, aangeboden partrevisies, missiecontext en output.
De geregistreerde verwerking, nieuwe state en toegestane acties moeten
consistent worden vastgelegd. Herstart mag dezelfde part niet ongemerkt
dubbel aanbieden of dezelfde missie dubbel uitsturen.

Een modelcall of langdurige filesystembewerking houdt geen SQLite
write-transactie open. De bestaande korte finale transactie en controle
van de oorspronkelijke queue-snapshot blijven uitgangspunten.

Operationele dag-audit vervalt momenteel na acht ISO-weken. Dat is niet
automatisch de bewaartermijn van een actief dossier. Actieve state, open
missies en benodigd bronbewijs moeten bereikbaar blijven zolang het
onderzoek loopt. Archivering en opruiming krijgen een apart beleid dat
zowel traceerbaarheid als beperkte schijfruimte bewaakt. Dit ontwerp wijzigt
de bestaande retentiejob nog niet.

## Volgende implementatiestappen

1. Ontwerp schema, migratie en crashherstel voor dagoverschrijdende week/topic-parts,
   met behoud van dagsnapshot, korte write-transactie en exacte provenance.
2. Bouw en test dat vlechtwerk, inclusief groei, overflow, retries, weekwissel
   en intacte eerder aangeboden versies.
3. Definieer Leonardo's state- en actieprotocol en de concrete callbouwer,
   tokenlimieten, aanbiedplanning en kostenadministratie.
4. Voeg Kuifje-missies en terugkeer naar expliciete dossiers toe, met aparte
   protocolversie, budgetreservering en opslag-/retentiebeleid.

Bella kan deze stappen later afzonderlijk uitvoeren op branches met PR's.
Deze documentatiewijziging verandert geen productiecode, cronjob, actieve
Sherlock-taak of inrichting van bibib.

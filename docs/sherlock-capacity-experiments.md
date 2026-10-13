# Sherlock-capaciteitsexperimenten

## Doel

Dit document beschrijft hoe we empirisch bepalen hoeveel werk één Sherlock-worker binnen één uur kan verzetten voordat een platform-, context-, token-, tool- of tijdslimiet bindend wordt.

De centrale vraag is niet: "wat is het theoretische contextvenster?", maar:

> Hoeveel nuttige inputverwerking, outputproductie en operationele stappen kan één Sherlock-run werkelijk uitvoeren voordat het systeem niet verder kan?

We behandelen capaciteit daarom als een vector van mogelijke grenzen, niet als één verondersteld tokenbudget.

## Status — 13 oktober 2026

Sherlock draait in een uurmodel. Iedere run behandelt exact één door de backend toegewezen topic en kan over meerdere afzonderlijke Code Mode-executies worden voortgezet met dezelfde `run_id`.

### Reeds empirisch vastgesteld

Eén afzonderlijke Code Mode-executie kan maximaal 20 onderliggende toolcalls uitvoeren.

Diagnose op 12 oktober 2026:
- één testscript probeerde 30 opeenvolgende `filter_sherlock_sources`-calls;
- exact 20 calls bereikten de Weekendkrant-backend en retourneerden HTTP 200;
- vóór de 21e backendcall stopte de executie met:
  `Code Mode exceeded the maximum number of tool calls.`

Dit bewijst uitsluitend een grens per Code Mode-executie. Het bewijst geen grens van 20 toolcalls per volledige Sherlock-run, taak of uur.

De productie-instructies gebruiken daarom maximaal 15 mogelijke onderliggende toolcalls per Code Mode-executie om marge onder het waargenomen plafond te houden.

### Nog niet empirisch vastgesteld

We kennen nog geen harde grens voor:
- cumulatieve inputtokens per uur-run;
- cumulatieve outputtokens per uur-run;
- maximale contextgrootte van één modelstap;
- aantal modelstappen binnen één run;
- aantal Code Mode-executies binnen één run;
- maximale wandkloktijd van één worker;
- eventuele gebruiks- of accountquota die een run kunnen stoppen;
- interacties tussen bovenstaande dimensies.

Sporadische safety-blocks worden voorlopig niet als capaciteitsgrens geïnterpreteerd. Zij zijn een afzonderlijk fenomeen met eigen telemetrie en retrybeleid.

## Begrippen

### Contextgrootte

De hoeveelheid context die één modelstap op dat moment ziet. Dit omvat onder meer vaste instructies en dynamisch opgebouwde runcontext.

### Cumulatieve input

De som van de inputtokens van alle modelstappen binnen één run.

Als opeenvolgende stappen bijvoorbeeld 10k, 20k en 30k inputtokens zien, is de cumulatieve input 60k, niet 30k.

Dit onderscheid is essentieel omdat eerder opgebouwde context in latere modelstappen opnieuw kan worden verwerkt.

### Cumulatieve output

De som van alle outputtokens die het model tijdens alle modelstappen van de run genereert.

### Zichtbare versus onbekende tokens

Waar mogelijk meten we zichtbare tekst met een expliciet vastgelegde tokenizer. Dat kan onder meer omvatten:
- Sherlock-instructies;
- zoekresultaten;
- geopende broninhoud voor zover zichtbaar;
- toolargumenten;
- toolresultaten;
- zichtbare modeloutput.

Platforminterne systeemcontext, verborgen reasoning, caching en andere niet-zichtbare overhead mogen niet worden verzonnen. Zij blijven als onbekende overhead gemarkeerd tenzij het platform exacte usage-telemetrie levert.

## Capaciteitsvector

Voor iedere run willen we minstens deze dimensies karakteriseren:

- **I** — cumulatieve inputtokens;
- **O** — cumulatieve outputtokens;
- **Cmax** — grootste waargenomen context van één modelstap;
- **M** — aantal modelstappen;
- **E** — aantal afzonderlijke Code Mode-executies;
- **K** — totaal aantal onderliggende toolcalls;
- **T** — verstreken wandkloktijd;
- **S** — concrete stopreden.

Een gemeten eindpunt is pas een harde grens voor een dimensie wanneer de zichtbare stopreden die grens daadwerkelijk identificeert of wanneer gecontroleerde herhaling dat overtuigend ondersteunt.

## Experimenteel principe

De worker moet voor capaciteitsmetingen voldoende werk krijgen om niet door een kunstmatig klein inhoudelijk doel te stoppen.

Een geschikte experimentele opdracht:
1. start één normale Sherlock-run;
2. werk uitsluitend binnen het toegewezen topic;
3. zoek, review, registreer en publiceer in kleine batches;
4. blijf nieuwe relevante batches verwerken zolang de taakomgeving dit toelaat;
5. start binnen dezelfde taak geen tweede Sherlock-run;
6. stop niet omdat een vooraf gekozen aantal van bijvoorbeeld 20 of 30 bronnen bereikt is wanneer nog zinvol, relevant werk beschikbaar is;
7. respecteer alle operationele en veiligheidsregels;
8. registreer de concrete reden waarom verder werken ophield.

Het doel is niet een limiet te omzeilen. Het doel is de limiet gecontroleerd te observeren.

## Meetmodel per stap

Idealiter loggen we per relevante model- of uitvoeringsstap:

```text
timestamp
run_id
topic
execution_index
step_index
action_type
visible_input_tokens
visible_output_tokens
estimated_context_tokens
tool_calls
elapsed_seconds
result
stop_reason
```

Mogelijke `action_type`-waarden:
- `search`
- `open_source`
- `filter_sources`
- `review_source`
- `record_source`
- `publish_fiche`
- `finish_run`
- `retry`
- `other`

Wanneer exacte tokenusage per modelstap niet beschikbaar is, bewaren we expliciet dat het om een reconstructie of schatting gaat.

## Eerste experimenten

### Experiment A — maximale nuttige duur

Laat één worker binnen één run bruikbaar onderzoek blijven uitvoeren zonder kunstmatige bronlimiet.

Meet:
- start- en eindtijd;
- aantal executies;
- aantal modelstappen;
- toolcalls;
- gereviewde bronnen;
- gepubliceerde fiches;
- zichtbare input/output;
- precieze stopreden.

Doel: vaststellen of wandkloktijd, taaklifecycle of een andere productlimiet eerst bindt.

### Experiment B — executiedichtheid

Gebruik kleine Code Mode-batches ruim onder de grens van 20 en vergelijk runs met verschillende batchgroottes.

Bijvoorbeeld:
- circa 5 mogelijke toolcalls per executie;
- circa 10;
- circa 15.

Doel: vaststellen of veel afzonderlijke executies andere limieten blootleggen dan grotere batches.

### Experiment C — contextgroei

Volg de zichtbare contextgroei tijdens één lange run.

Meet of latere stappen merkbaar duurder worden doordat eerder verzamelde context opnieuw meegedragen wordt.

Doel: onderscheiden:
- maximale context per modelstap;
- cumulatieve input over de volledige run.

### Experiment D — input versus output

Vergelijk runs met vergelijkbare zoekdekking maar verschillende vereiste outputcompactheid, voor zover dit redactioneel verantwoord kan zonder andere variabelen sterk te veranderen.

Doel: aanwijzingen krijgen of input-, output- of algemene compute-usage als eerste bindt.

### Experiment E — gecontroleerde herhaling

Een enkel stopmoment is een datapunt, geen algemene limiet.

Herhaal relevante configuraties totdat een grens reproduceerbaar is. Noteer altijd:
- exacte fouttekst of stopmelding;
- welk werk vlak ervoor plaatsvond;
- welke calls wel bevestigd waren;
- tijd en run-id;
- relevante configuratie.

## Interpretatieregels

### Geen limiet afleiden uit een gewone voltooiing

Als Sherlock stopt omdat er geen relevante bronnen meer gevonden worden of omdat de instructie zegt dat het werk voltooid is, zegt dat niets over maximale capaciteit.

### Geen tokenlimiet afleiden uit een toolfout

Een toolcallbudgetfout bewijst een toolcallgrens, niet een tokenbudget.

### Geen capaciteitslimiet afleiden uit een safety-block

Een safety-block is alleen bewijs voor het safetyfenomeen. Het huidige retrybeleid blijft daarvan de operationele behandeling.

### Eén fout is nog geen universele productgrens

Waar mogelijk moet een grens opnieuw worden geraakt met dezelfde of gecontroleerd gewijzigde omstandigheden.

### Verander één belangrijke dimensie tegelijk

Na het vinden van een mogelijke bottleneck varieert het volgende experiment bij voorkeur één hoofdvariabele. Zo kunnen causale hypotheses worden onderscheiden.

## Run-samenvatting voor capaciteitsonderzoek

Voor experimentele runs willen we uiteindelijk minstens kunnen rapporteren:

```text
run_id:
topic:
start:
end:
elapsed:
registered_sources:
published_fiches:
queue_item_ids:
model_steps:
code_mode_executions:
tool_calls:
visible_input_tokens:
visible_output_tokens:
max_visible_context_tokens:
stop_reason:
exact_error_if_any:
measurement_quality:
notes:
```

`measurement_quality` kan bijvoorbeeld `exact`, `reconstructed` of `estimated` zijn.

## Eerste doel

De eerstvolgende fase is niet optimaliseren maar karakteriseren.

We willen voldoende runs verzamelen om per mogelijke bottleneck te kunnen zeggen:
- nog niet geraakt;
- eenmaal waargenomen;
- reproduceerbaar;
- harde grens voldoende aangetoond.

Pas daarna veranderen we Sherlock structureel om zo dicht mogelijk tegen de aangetoonde grenzen te werken zonder capaciteit ongebruikt te laten en zonder de betrouwbaarheid van bronregistratie, fichepublicatie of runafsluiting te verminderen.

## Relatie met andere documentatie

- [Sherlock-instructies](agents/sherlock.md): operationeel gedrag van de worker.
- [Token- en kostenstrategie](token-and-cost-strategy.md): bredere token- en kostenarchitectuur, vooral voor Leonardo en latere modelcalls.
- Dit document: empirische karakterisering van de feitelijke capaciteit van Sherlock als actieve worker.

# Redactionele principes

## Bronnen boven een mooi verhaal

Een overtuigend narratief mag nooit de ontbrekende schakel tussen twee bronnen invullen alsof die bewezen is.

Leonardo mag verbanden voorstellen en patronen benoemen, maar moet onderscheid bewaren tussen:

- rechtstreeks gerapporteerde feiten;
- convergerend bewijs uit meerdere bronnen;
- inferenties;
- zwakke signalen;
- speculatie;
- tegenstrijdige informatie.

## Bronbreedte en onafhankelijke bevestiging

In het doelontwerp bewaakt Leonardo op dossier-/verhaalniveau de breedte en
onafhankelijkheid van bronnen en perspectieven. Hij kijkt waar relevant naar
spreiding over bronsoorten, instellingen, regio's, talen en betrokken perspectieven.
Meerdere publicaties die hetzelfde persbericht of dezelfde oorspronkelijke bron
herhalen, vormen geen onafhankelijke bevestiging. Spreiding volgt de inhoudelijke
vraag en bronkwaliteit; aantallen of geforceerde balans zijn geen kwaliteitsbewijs.

Ontbreekt relevante spreiding of onafhankelijke bevestiging, dan mag Leonardo
een begrensde Kuifje-missie voorstellen om dat concrete gat gericht te onderzoeken.
Sherlock blijft breed scouten. Ariadne bewaart en routeert de expliciete opdracht
en bewaakt de technische grenzen; zij beoordeelt inhoudelijke lacunes nooit zelf.
Zie het [missieontwerp](leonardo-memory-and-orchestration.md#kuifje-keert-terug-naar-hetzelfde-dossier).

## Sherlock comprimeert, maar synthetiseert niet breed

Sherlock moet webmateriaal reduceren tot compacte, bruikbare bronfiches. Hij mag relevantie inschatten, maar moet niet vooruitlopen op Leonardo's latere synthese.

Iedere fiche moet de oorspronkelijke bron traceerbaar houden.

## Fouten moeten zacht falen

Een semantische fout van een model mag de technische pipeline niet neerhalen.

De deterministische laag bewaakt alleen technische invarianten. Inhoudelijke fouten worden via kwaliteitslabels en gerichte herstelstappen behandeld.

## Geen regressielussen

Meer controle is niet automatisch meer betrouwbaarheid. Een eindeloze reeks modellen die elkaars werk opnieuw controleren:

- kost extra tokens;
- creëert nieuwe kansen op fouten;
- maakt provenance onduidelijk;
- levert geen wiskundige garantie op waarheid.

Daarom stopt de standaardketen na maximaal één Minos-herschrijving.

## Menselijke inspectie blijft mogelijk

SQLite bewaart nieuwe fiches in de persistente transportqueue; Git/GitHub bewaart
code en ontwerpdocumentatie. De lokale SQLite-audit bewaart de operationele
provenance van de deterministische backlogverwerking. Historische Git-fiches
blijven bewaard, maar zijn geen actuele consumenteninvoer.
Bij uitzonderlijke, verrassende of twijfelachtige claims moet het gemakkelijk zijn om
van een afgeleid resultaat terug te gaan naar de gebruikte bronfiches en hun
oorspronkelijke bronnen.

## Kwaliteit boven snelheid

Weekendkrant hoeft geen breaking-newsmachine te zijn. Het weekendritme laat toe informatie gedurende de week te verzamelen en pas daarna patronen, correcties en context te verwerken.

## Architectuur mag klein beginnen

Nieuwe automatisering wordt alleen toegevoegd wanneer een concrete behoefte aantoonbaar bestaat. Vermijd preventief complexe databases, semantische zoeklagen, workflow-engines en extra agents.

Een lokale SQLite-database voor transportqueue en verwerkingsaudit is een bewuste keuze: daar is
een concrete behoefte aan herstartbare status, provenance en inspecteerbaarheid zonder
afgeleide runtimegegevens in Git te moeten bewaren.

Het doel is geen veelkoppige hydra, maar een reeks eenvoudige componenten met duidelijke verantwoordelijkheden.

# Weekendkrant

Weekendkrant is een experimentele, grotendeels geautomatiseerde nieuwsredactie voor een persoonlijk weekendmagazine.

Het systeem is bewust opgesplitst in een reeks smalle rollen:

- **Sherlock** verzamelt nieuws, doet een eerste lichte triage en vat bronnen compact samen.
- **Ariadne** is volledig deterministisch en vlecht Sherlocks output tot thematische draden met een harde tokenlimiet.
- **Leonardo** maakt van die draden inhoudelijke syntheses en verhalen.
- **Striktland** controleert of feitelijke claims door het aangeleverde bronmateriaal worden gedragen.
- **Minos** herschrijft alleen wanneer Striktland een probleem vindt en velt daarmee het eindoordeel.

De kernprincipes zijn:

1. webvergaring zoveel mogelijk uitvoeren binnen reeds inbegrepen ChatGPT-capaciteit;
2. deterministische verwerking tussen verzameling en dure modelcalls plaatsen;
3. intelligente modellen zo weinig mogelijk irrelevante tokens laten lezen;
4. feitelijke claims traceerbaar houden naar bronmateriaal;
5. kwaliteitscontrole eindig houden: geen oneindige regressielussen;
6. de hele keten auditeerbaar maken.

Zie de ontwerpdocumentatie:

- [Architectuur](docs/architecture.md)
- [Rollen: Sherlock, Ariadne, Leonardo, Striktland en Minos](docs/roles.md)
- [Token- en kostenstrategie](docs/token-and-cost-strategy.md)
- [Audit trail en kwaliteitslabels](docs/audit-trail.md)
- [Redactionele principes](docs/editorial-principles.md)

## Status

De geïmplementeerde taak is Ariadnes **wekelijkse weekvoorbereiding op origin**:
een ISO-weekbranch, een ingressmap en een herhaalbaar auditrecord. Bronfiches verwerken, draden vlechten
en modelcalls zijn nog niet geïmplementeerd.

De eerstvolgende Ariadne-fase blijft bewust observerend. Sherlocks bronfiches blijven
op de wekelijkse ingressbranch staan; Ariadne zal daar lokaal reproduceerbare
Leonardo-inputs van maximaal 35.000 tokens uit afleiden. Die afgeleide draden hoeven
tijdens deze proefperiode niet terug naar GitHub: ze mogen lokaal opnieuw opgebouwd
en weggegooid worden. Verwerkingsstatus en provenance worden lokaal in SQLite
bijgehouden.

## Weekwerkruimte voorbereiden

Python 3.9 of nieuwer, Git en een lokale clone volstaan; er zijn geen Python-dependencies.
De installatie staat onder `/home/weekendkrant/app`. Maak daar eenmalig de venv aan:

```bash
cd /home/weekendkrant/app
python3 -m venv .venv
```

Normale gebruikers en toekomstige cronjobs starten Ariadne via `start_ariadne.sh`.
Beide uitvoerscripts gaan eerst naar de vaste repositoryroot en gebruiken rechtstreeks
`/home/weekendkrant/app/.venv/bin/python`; handmatig activeren van `.venv` is niet nodig.
Een ontbrekende venv/interpreter geeft een shellfout en een niet-nul exitcode.
Voer vanuit de repositoryroot uit:

```bash
./start_ariadne.sh prepare-week --date 2026-10-04
```

Dit bereidt `ingress/2026_W40` voor, met `ingress/2026_W40/.gitkeep`
en `audit/2026_W40/ingress-preparation.json`, en pusht de branch naar `origin`.
`--date` gebruikt exact de opgegeven kalenderdatum en de bijbehorende ISO-week.
De wekelijkse zondagavondtaak gebruikt in plaats daarvan:

```bash
/home/weekendkrant/app/start_ariadne.sh prepare-week --next-week
```

`--next-week` bepaalt de actuele datum expliciet in `Europe/Brussels` en kiest
de maandag van de eerstvolgende ISO-week. `--date` en `--next-week` zijn wederzijds
exclusief; één van beide is verplicht. De oude aanroep zonder subcommand vervalt.

De taak vereist een schone werkboom, haalt `origin` op en werkt lokale `main`
uitsluitend fast-forward bij tot `origin/main`. Nieuwe weekbranches beginnen op
die actuele `main`; bestaande lokale of remote weekbranches worden veilig hergebruikt.
Ariadne commit alleen de twee voorbereidingsbestanden indien nodig en pusht de
weekbranch met upstream. Git-identiteit en niet-interactieve lees-/schrijfauthenticatie
voor `origin` moeten vooraf zijn ingesteld. Alleen een geslaagde push geldt als succes.

Herhalen bewaart oogst en auditrecord en maakt geen nutteloze extra commit.
Een vuile werkboom, conflicterende metadata, divergente of lokaal vooruitgelopen
`main`, of een weekremote die vooruitloopt/divergeert leidt tot stoppen.
Er is geen force-push, reset, automatische conflictmerge of weggooien van lokale
wijzigingen. Gebruik één schrijver per clone. Bij een pushfout blijft een gemaakte
commit lokaal behouden; na herstel van de fout kan dezelfde taak opnieuw worden uitgevoerd.

Runtime-meldingen verschijnen in `/home/weekendkrant/logs/ariadne.log`, met
automatische rotatie (1 MiB, vier reservebestanden; circa 5 MiB totaal).
Het JSON-resultaat blijft als gestructureerde CLI-output op stdout verschijnen.
De uitvoerende gebruiker moet de logmap kunnen aanmaken of erin kunnen schrijven;
zie [de loggingconfiguratie](docs/architecture.md#logging).

De handmatige preflight van `prepare-week --next-week` op `bibib` is geslaagd;
de weekbranch staat op GitHub en de wekelijkse cronjob is ingesteld voor zondag
om 22:00 Belgische tijd. Zie [het weekritme](docs/architecture.md#zondagavond-en-overgang-naar-de-volgende-week).

Voor de nog te implementeren dagelijkse taak is afgesproken: één cronstart om
10:00 Belgische tijd, waarna Ariadne zelf elke tien minuten op Sherlocks expliciete
gereedmelding voor die dag controleert, maximaal drie uur. Ze verwerkt uitsluitend
een afgesloten dagoogst en bewaart succes of fouten in SQLite. Dagfouten zijn
leesbaar voor de weekjob, maar blokkeren de volgende weekvoorbereiding niet.
Vorige weken worden niet ingehaald. Zie
[het dagafsluitingscontract](docs/architecture.md#dagafsluiting-en-dagelijkse-uitvoering-afgesproken-ontwerp).
Dagelijkse verwerking, gereedmeldingen, de gedeelde vergrendeling, `weave`, SQLite
en tokenmeting zijn nog niet geïmplementeerd; ook Sherlocks actieve taak moet nog
aan het gereedmeldingscontract worden aangepast.

```bash
./start_tests.sh
```

Zie [de afbakening van deze stap](docs/architecture.md#eerste-implementatiestap-weekvoorbereiding)
en [het voorbereidingsrecord](docs/audit-trail.md#weekvoorbereiding-schema-1).

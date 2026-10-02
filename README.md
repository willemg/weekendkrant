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

Geïmplementeerd zijn Ariadnes wekelijkse voorbereiding en dagelijkse deterministische
verwerking van Sherlocks afgesloten oogst. De dagelijkse taak pollt de remote,
valideert het afsluitmanifest, maakt lokale thematische draden en registreert status
en provenance in SQLite. Er zijn geen modelcalls.

Zie [dagelijkse runtime en handmatige controles voor bibib](docs/daily-runtime.md)
en [de exacte aanvulling voor Sherlock](docs/sherlock-dagafsluiting.md).
De dagelijkse cronregel is alleen gedocumenteerd, nog niet geïnstalleerd.

## Weekwerkruimte voorbereiden

Python 3.9 of nieuwer, Git en een lokale clone zijn vereist. Dagelijkse verwerking
gebruikt daarnaast de vastgelegde tokenizer uit `requirements.txt`.
De installatie staat onder `/home/weekendkrant/app`. Maak daar eenmalig de venv aan:

```bash
cd /home/weekendkrant/app
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
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

Dagelijks handmatig starten:

```bash
./start_ariadne.sh daily
```

Dit kiest vandaag in `Europe/Brussels`, wacht maximaal drie uur op Sherlock en
verwerkt alleen de expliciet afgesloten dag. Succes, timeout en verwerkingsfouten
blijven in SQLite bewaard. De zondagavondjob rapporteert onvolledige dagen zonder
de volgende weekvoorbereiding te blokkeren. Beide taken gebruiken hetzelfde slot.
Volg eerst de [preflight](docs/daily-runtime.md#handmatig-controleren-op-bibib--vóór-croninstallatie),
inclusief tokenizer-cache en de handmatige workflowtest.

```bash
./start_tests.sh
```

Zie [de afbakening van deze stap](docs/architecture.md#eerste-implementatiestap-weekvoorbereiding)
en [het voorbereidingsrecord](docs/audit-trail.md#weekvoorbereiding-schema-1).

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

De eerste implementatiestap is Ariadnes **lokale weekvoorbereiding**: een ISO-weekbranch,
een ingressmap en een herhaalbaar auditrecord. Bronfiches verwerken, draden vlechten
en modelcalls zijn nog niet geïmplementeerd.

De eerstvolgende Ariadne-fase blijft bewust observerend. Sherlocks bronfiches blijven
op de wekelijkse ingressbranch staan; Ariadne zal daar lokaal reproduceerbare
Leonardo-inputs van maximaal 35.000 tokens uit afleiden. Die afgeleide draden hoeven
tijdens deze proefperiode niet terug naar GitHub: ze mogen lokaal opnieuw opgebouwd
en weggegooid worden. Verwerkingsstatus en provenance worden lokaal in SQLite
bijgehouden.

## Weekwerkruimte voorbereiden

Python 3.9 of nieuwer, Git en een lokale clone volstaan; er zijn geen Python-dependencies.
Voer vanuit de repositoryroot uit (na opname van deze implementatie):

```bash
git fetch origin
python3 ariadne.py --date 2026-09-30
```

Dit selecteert of maakt lokaal `ingress/2026_W40`, met `ingress/2026_W40/.gitkeep`
en `audit/2026_W40/ingress-preparation.json`. De datum is expliciet: geef de lokale
kalenderdatum mee; ISO-weekjaar en weeknummer worden daaruit afgeleid.
Een bestaande lokale weekbranch krijgt voorrang, vervolgens een reeds opgehaalde
remote weekbranch. Een nieuwe branch begint op lokale `main`; werk die vooraf bij.
Bij branchwissel moet de werkboom schoon zijn. Herhalen op dezelfde weekbranch
bewaart oogst en auditrecord. Gebruik één schrijver per clone.

Runtime-meldingen verschijnen in `/home/weekendkrant/logs/ariadne.log`, met
automatische rotatie (1 MiB, vier reservebestanden; circa 5 MiB totaal).
Het JSON-resultaat blijft als gestructureerde CLI-output op stdout verschijnen.
De uitvoerende gebruiker moet de logmap kunnen aanmaken of erin kunnen schrijven;
zie [de loggingconfiguratie](docs/architecture.md#logging).

Bekijk daarna de wijzigingen, commit de voorbereidingsbestanden en push de weekbranch
als Sherlock de werkruimte op GitHub moet kunnen gebruiken. Het script doet zelf geen
fetch, commit, push, PR of merge en wijzigt `main` niet.

```bash
python3 -m unittest discover -s tests -v
```

Zie [de afbakening van deze stap](docs/architecture.md#eerste-implementatiestap-weekvoorbereiding)
en [het voorbereidingsrecord](docs/audit-trail.md#weekvoorbereiding-schema-1).

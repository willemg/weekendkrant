# Impactgedreven tests

`./start_tests.sh` selecteert standaard impacttests; `./start_tests.sh --all`
draait alle Python-tests zoals de oude unittest-discovery. Onbekende argumenten
falen. Het script werkt vanuit zijn eigen checkout, gebruikt `.venv/bin/python`
indien aanwezig, anders `python3`. De bestaande bibib-tokenizercache blijft de
standaard via `$HOME/.cache/tiktoken`; expliciete cacheconfiguratie gaat voor.

`test_impact.py` gebruikt `git merge-base origin/main HEAD` (lokale `main` als er
geen remote tracking ref is). De diff vergelijkt de merge-base met de worktree,
inclusief staged/unstaged wijzigingen; untracked files worden toegevoegd.
Renames zijn delete+add. Fetch `origin/main` vóór branchwerk: de runner doet
bewust geen netwerkoperatie of wijziging aan Git-refs tijdens iedere testronde.
Een ontbrekende merge-base of Git-fout geeft full-suite fallback.

De selector parseert Python AST-imports, inclusief imports binnen functies en
bekende literal dynamic imports, bouwt reverse dependencies en loopt transitief
van iedere gewijzigde file naar tests. Gewijzigde tests worden zelf meegenomen.
Iedere geselecteerde module toont de gewijzigde oorzaken of de fallbackreden;
vóór uitvoering verschijnt het aantal modules en daadwerkelijk geladen tests.

Een kleine expliciete lijst van componentgrenzen voegt dispatcher-, HTTP- en
systeemtests toe. Die lijst vervangt geen importgraph. Wijzigingen aan database,
migraties, requirements, runtimeconfiguratie, package-initialisatie,
testinfrastructuur/selector of uitvoerbare agentcontracten draaien alles.
Ook breed geïmporteerde modules, onoplosbare/deleted files, parsefouten,
onbegrensde dynamische imports en onbekende niet-Python-grenzen draaien alles.
Productcode zonder bereikbare test wordt nooit als nul impact behandeld.
Gewone documentatiewijzigingen kunnen wel nul tests selecteren.

AST-analyse bewijst geen volledige runtimeafhankelijkheid. Dynamische grenzen
moeten expliciet blijven; bij nieuwe mechanismen zonder betrouwbare begrenzing
is full-suite fallback vereist. De fixturetests in `test_test_impact.py` testen
selectie onafhankelijk van de bestandsnamen van deze PR, met echte Git-branches,
advanced main, werkboomwijzigingen en untracked files.

De huidige PR wijzigt selector én schema en kiest daarom alle testmodules.
Er wordt voor deze PR geen snelheidswinst geclaimd; kleinere volgende branches
krijgen automatisch een andere selectie. Een volledige `--all`-run blijft
verplicht voordat een PR klaar is voor review.

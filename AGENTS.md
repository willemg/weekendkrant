# Ontwikkelcontract

Lees vóór iedere fase of functionele PR het [technisch leerlog en de blijvende
ontwikkelregels](docs/lessons-learned.md), in het bijzonder het
[fast-trackcontract](docs/test-fast-track.md).

Werk op een branch vanaf actuele main, met TDD; commit niet op main.
Iedere functionele PR moet `tests/fast_track.txt` expliciet beoordelen en bij
gewijzigde testimpact aanpassen, inclusief nieuwe tests en geraakte bestaande
regressie-, integratie- en systeemtests. De lijst representeert de laatst
samengevoegde functionele wijziging; de volgende PR mag en moet hem opnieuw aan
zijn eigen impact aanpassen. Zonder die beoordeling is een PR niet reviewklaar.

Gebruik tijdens normale ontwikkeling, TDD en PR-validatie uitsluitend
`./start_tests.sh`; dit is ook de normale post-pull/deploymenttest.
Draai `./start_tests.sh --all` niet standaard vóór review of merge. Een volledige
suite draait alleen als de opdracht dit expliciet vraagt of bij een concrete
uitzonderlijke technische reden. Vermeld die reden wanneer je daarom toch
`--all` uitvoert. Dat `--all` beschikbaar blijft, verplicht geen enkele PR om
hem standaard uit te voeren.
Houd bibib en zijn Python-tests Node-vrij; pluginchecks horen bij de pluginlaag.

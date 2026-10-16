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

Gebruik `./start_tests.sh` voor ontwikkeling en normale post-pull/deploymenttests.
`./start_tests.sh --all` blijft beschikbaar voor expliciete volledige regressie.
Houd bibib en zijn Python-tests Node-vrij; pluginchecks horen bij de pluginlaag.

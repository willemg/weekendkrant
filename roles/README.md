# Runtimecontracten

Deze bestanden zijn productie-input, geen afzonderlijke scheduled agents.
Zie [contractgrens, opslag en begrippen](../docs/roles.md#runtimecontracten-fase-85).
Nieuwe jobs snapshotten exacte UTF-8-inhoud plus SHA-256-refs; bestaande jobs
blijven hun immutable contractversie uitvoeren. Bewerk hiervoor de role- en
outputfiles, niet de generieke [executor](../executor/instructions.md).
Er worden geen placeholders voor toekomstige rollen aangemaakt.

## Runtimecontracthygiëne

Alle natuurlijke-taalinstructies in role- en outputcontracten staan in het
Nederlands. Exacte technische identifiers, toolnamen, veldnamen, enumwaarden en
letterlijke externe foutmeldingen blijven ongewijzigd waar hun exacte vorm deel
uitmaakt van het contract.

Een runtimecontract is epistemisch gesloten: het verwijst alleen naar informatie
die de worker werkelijk aangeleverd krijgt, expliciet beschikbare tools en de
beslissingen die binnen die job genomen moeten worden. Architectuurmotivatie,
verantwoordelijkheden van andere rollen, toekomstige rollen, historische
incidenten en andere ontwikkelcontext horen in `docs/`, niet in `roles/`.

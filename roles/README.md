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


Beoordeel een rolefile nooit op zichzelf. Leg vóór activering de generieke
executorinstructie, het echte jobpakket, rolecontract, outputcontract, zichtbare
toolnamen/descriptions/schema's en mogelijke inhoudelijke input naast elkaar en
voer de samengestelde-contextaudit uit zoals beschreven in
[docs/roles.md](../docs/roles.md#samengestelde-contextaudit).

Gebruik geen handmatige `v1`/`v2`-labels in role- of outputcontracten. Git,
de immutable contractsnapshot en de SHA-256-ref identificeren de concrete
contractinhoud. Een `schema_version` in machine-output is daarvan losstaand en
blijft alleen waar het dataschema die waarde vereist.

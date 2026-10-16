# Versioned runtimecontracten

Deze bestanden zijn productie-input, geen afzonderlijke scheduled agents.
Zie [contractgrens, opslag en begrippen](../docs/roles.md#runtimecontracten-fase-85).
Nieuwe jobs snapshotten exacte UTF-8-inhoud plus SHA-256-refs; bestaande jobs
blijven hun immutable contractversie uitvoeren. Bewerk hiervoor de role- en
outputfiles, niet de generieke [executor](../executor/instructions.md).
Er worden geen placeholders voor toekomstige rollen aangemaakt.

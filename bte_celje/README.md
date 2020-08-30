BTE Celje - Navodila
====================

Opozorilo
---------

Ta navodila so namenjena vsem, ki nameravajo graditi Celje oz. okolico, in sicer naslednje območje.

![Območje gradnje](map.jpg)

Obrazložilo
-----------

Kot ste že mogoče opazili, je natančnost terena, ki jo generira Terra z pomočjo AWS Terrain Tiles, zelo slaba. Da bi se izognili temu, sem se odložil uporabit LIDAR podatke. Ker ti vsebujejo tudi podatke o zgradbah in vegetaciji, sem najprej trebal izluščiti le teren iz teh LIDAR podatkov ki jih najdemo na arso. Več o tem lahko izveste [tukaj](https://github.com/DavixDevelop/TerraLidar). Skratka, ko dobimo podatke v pravilnem formatu, za Terra, jih lahko uprabimo, ampak, ker Terra ne podpira pomeri podatkov za teren, uporabimo nadgradnjo Terra, tako imenovan Terra++. Več o tem izveste [tukaj](https://github.com/bitbyte2015/terraplusplus).

Navodila
--------

- Sledimo tipični namestitvi za BTE
- Ko namestimo vse potrebno prenesemo Terra++ iz naslednje [povezave](https://github.com/bitbyte2015/terraplusplus/releases)
- V raziskovalcu odpremo mesto kjer imamo nameščene razširitve (npr. C:\Users\david\AppData\Roaming\.minecraft\mods)
- V mapo kopiramo Terra++ in jo zamenjamo že z obostoječo datoteko
- V raziskovalcu pod Dokumenti, ustvarimo novo mapo Minecraft, in v njej mapo CustomTerrain (npr. C:\Users\david\Documents\Minecraft\CustomTerrain)
- Iz naslednje [povezave](https://1drv.ms/u/s!ApjeN2QtEv53tLkNCeJsH0AkonG59w?e=rRyivr) prenesemo stisnjeno mapo v zgoraj omenjeno mapo (CustomTerrain)
- Preneseno stisnejno mapo razširimo v mapo CustomTerrain. Po razširitvi stisnjene mape se v mapi CustomTerrain pojavi mapa Flats
- Odpremo Minecraft in ustvarimo novi svet po običajnih BTE nastavitvah
- Pod Custom Terrain možnost izberemo DA
- v textovno polje spodaj vnesemo pot do CustomTerrain/Flats, le da pazimo, da namesto \ uporabimo / in prav tako na koncu poti prav tako dodamo / (npr. C:/Users/david/Documents/Minecraft/CustomTerrain/Flats/)

![Terra++ nastavitve](nastavitve.jpg)

- Ko ustvarimo svet, se z ukazom /tpll 46.225556, 15.266604 premestimo v Celje
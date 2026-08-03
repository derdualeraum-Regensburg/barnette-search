# hsep-Erklärgrafik für den Barnette-Graphen n=14

- Kanonischer Graph-SHA-256: `3b52365d8f69db960762343efece3b7510b943660d0fbd6353bb4f4cd7c0f445`
- Ungerichtete Hamiltonkreise insgesamt: **12**
- Exakter Wert: **hsep(G)=10**
- Ausgewählte Zyklen des vorhandenen Primalzertifikats: **1, 2, 3, 4, 5, 7, 8, 10, 11, 12**
- Nicht benötigte Zyklen: **6, 9**

Die Hauptgrafik zeigt den Grundgraphen und alle zwölf Hamiltonkreise. Im zentralen 21×21-Trennzeugnis steht in Feld (e,f) ein ausgewählter Zyklus, der die Zeilenkante e enthält und die Spaltenkante f meidet. Alle 420 Felder außerhalb der Diagonale sind ausschließlich mit Zyklen des zertifizierten 10er-Primalzertifikats belegt; C6 und C9 werden nicht verwendet. Die kleine 0/1-Matrix zeigt ergänzend alle zwölf Zyklen mit C6 und C9 als graue Kontextspalten. Die Aussage, dass neun Zyklen nicht genügen, stützt sich auf das vorhandene exakte Lower-Bound-Zertifikat mit 4.017 geprüften Teilmengen; sie wird nicht aus der Grafik abgeleitet.

Alle Graphteilbilder verwenden die Koordinatenbasis `72d2463d2a0d6b4e49a041d00df810b007dca13cd52fab22cd5544f9f56ae2ca` aus dem vorhandenen n=14-Atlas und unterscheiden sich nur durch uniforme Skalierung und Translation.

## Dateien

- `hsep_n14_explained.svg`, `.png`, `.pdf`: didaktische Hauptgrafik
- `selected_10_cycles.json`: extrahiertes Primalzertifikat
- `signature_matrix.csv`: zertifizierte 21×10-Kantensignaturen; die Grafik ergänzt C6 und C9 grau als Kontext
- `didactic_figure_verification.json`: maschinenlesbare Qualitätsprüfung
- `build_hsep_explainer.py`: reproduzierbarer Builder

## Reproduktion

```powershell
python build_hsep_explainer.py --source ..\n14_all_hamiltonian_cycles_20260803_194908 --output .
```

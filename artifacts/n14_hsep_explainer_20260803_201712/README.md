# hsep-Erklärgrafik für den Barnette-Graphen n=14

- Kanonischer Graph-SHA-256: `3b52365d8f69db960762343efece3b7510b943660d0fbd6353bb4f4cd7c0f445`
- Ungerichtete Hamiltonkreise insgesamt: **12**
- Exakter Wert: **hsep(G)=10**
- Ausgewählte Zyklen des vorhandenen Primalzertifikats: **1, 2, 3, 4, 5, 7, 8, 10, 11, 12**
- Nicht benötigte Zyklen: **6, 9**

Die Hauptgrafik zeigt den Grundgraphen, alle zwölf Hamiltonkreise mit der zertifizierten 10er-Auswahl sowie die 21×10-Signaturmatrix. Die Signaturen sind paarweise inkomparabel. Die Aussage, dass neun Zyklen nicht genügen, stützt sich auf das vorhandene exakte Lower-Bound-Zertifikat mit 4.017 geprüften Teilmengen; sie wird nicht aus der Grafik abgeleitet.

Alle Graphteilbilder verwenden die Koordinatenbasis `72d2463d2a0d6b4e49a041d00df810b007dca13cd52fab22cd5544f9f56ae2ca` aus dem vorhandenen n=14-Atlas und unterscheiden sich nur durch uniforme Skalierung und Translation.

## Dateien

- `hsep_n14_explained.svg`, `.png`, `.pdf`: didaktische Hauptgrafik
- `selected_10_cycles.json`: extrahiertes Primalzertifikat
- `signature_matrix.csv`: 21 Kantensignaturen bezüglich der zehn ausgewählten Zyklen
- `didactic_figure_verification.json`: maschinenlesbare Qualitätsprüfung
- `build_hsep_explainer.py`: reproduzierbarer Builder

## Reproduktion

```powershell
python build_hsep_explainer.py --source ..\n14_all_hamiltonian_cycles_20260803_194908 --output .
```

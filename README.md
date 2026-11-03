# Frigate Virtual Radar

Zet de persoonskaders van een Frigate-camera om naar X/Y-posities op je plattegrond, als sensoren in Home Assistant. [Radar Map Manager](https://github.com/Moe8383/radar_map_manager) (RMM) ziet zo'n camera als een gewone mmWave-radar, dus je kunt camera's en radars samen gebruiken op één kaart en er zones op tekenen.

*English summary: turns Frigate person boxes into X/Y targets (`sensor.<radar>_target_N_x/_y`) on a floor plan via a 4-point floor calibration, so Radar Map Manager treats the camera as a radar. Configured fully from the UI.*

## Hoe het werkt

1. Frigate stuurt per gedetecteerd object een kader via MQTT (`frigate/events`).
2. Het voetpunt is het midden van de onderkant van het kader. Daar staat de persoon op de vloer.
3. Een **homografie** rekent dat voetpunt om naar een plek op je plattegrond. Je stelt hem eenmalig in door vier vloerpunten aan te klikken: in het camerabeeld én op de plattegrond.
4. De integratie maakt sensoren in het formaat dat RMM verwacht.

Losse onderdelen, geen afhankelijkheid van RMM-code: zonder RMM blijven de sensoren gewoon werken.

## Installeren

1. HACS (of de Marketplace vanaf HA 2026.11) → ⋮ → **Custom repositories** → `https://github.com/SilverApe/frigate-virtual-radar`, type **Integration**.
2. Download **Frigate Virtual Radar** en herstart Home Assistant.
3. **Instellingen → Apparaten & diensten → Integratie toevoegen → Frigate Virtual Radar**.

Vereist: de MQTT-integratie, en Frigate die naar dezelfde MQTT-broker publiceert.

## Instellen

| Veld | Betekenis |
|---|---|
| Frigate-camera | Cameranaam zoals in Frigate (`camera_01`) |
| Radarnaam in RMM | Bepaalt de entity-ID's, bijv. `cam01` → `sensor.cam01_target_1_x` |
| Max. personen | Aantal target-plekken (1–5, RMM leest er maximaal 5) |
| Labels die als persoon tellen | Meestal `person` |
| Label hond | `dog` geeft aparte hond-sensoren; leeg = uit. Honden komen nooit in de persoonsplekken |
| Minimale beweging | Kleinere verplaatsingen worden niet weggeschreven (minder database-schrijfacties) |
| Object vergeten na | Vangnet als Frigate geen "end" stuurt |
| Kalibratie | JSON uit de kalibratietool (mag eerst leeg blijven) |

Alles behalve camera en radarnaam pas je later aan via **Configureren**.

### Kalibratie-JSON

```json
{
  "camera": "camera_01",
  "image_size": [1920, 1080],
  "points": [
    {"img": [412, 988], "plan": [5.10, 7.20]},
    {"img": [1530, 1002], "plan": [7.85, 7.25]},
    {"img": [1290, 520], "plan": [7.80, 3.40]},
    {"img": [640, 505], "plan": [4.95, 3.35]}
  ],
  "origin": [6.40, 9.90]
}
```

- `image_size`: de **detect**-resolutie van de camera in Frigate.
- `img`: pixels in die resolutie. `plan`: meters op de plattegrond (X naar rechts, Y naar beneden, zoals de PNG).
- `origin`: de plek van de camera op de plattegrond. Dit wordt het nulpunt van de virtuele radar.
- Vier of meer punten, op de vloer, niet drie op één lijn. Bij meer punten wordt de beste passing berekend.

## Sensoren

| Entiteit | Inhoud |
|---|---|
| `sensor.<radar>_target_<n>_x` / `_y` | Positie in cm t.o.v. de camera (x naar rechts, y omhoog op de kaart). Leeg (`unknown`) als de plek vrij is |
| `sensor.<radar>_presence_target_count` | Aantal personen in beeld |
| `sensor.<radar>_dog_<n>_x` / `_y`, `sensor.<radar>_dog_count` | Hetzelfde voor de hond (RMM negeert deze namen) |

Attributen op de `_x`-sensor: `label`, `sub_label` (gezichtsherkenning), `score`, `stationary`, `zones`, `plan_x_m`, `plan_y_m`, `frigate_id`.

## In Radar Map Manager

1. Layout → **+** → naam `cam01` (de radarnaam, zonder achtervoegsel).
2. Zet de radar op de plek van de camera (`origin`). Rot **0**, **Mirror uit**.
3. Type **2.5D**: dan past RMM geen hoogtecorrectie toe, onze punten liggen al op de vloer. Bij "2D" corrigeert RMM voor montagehoogte en verschuift alles.
4. **ScX/ScY** gelijk aan de kaartschaal uit Set (bijv. 1 m = 9,71 % en 7,88 %), zodat 1 m bij de radar 1 m op de kaart is.

## Database ontzien

Posities veranderen vaak. Neem ze bij voorkeur niet op in de geschiedenis:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.*_target_*_x
      - sensor.*_target_*_y
      - sensor.*_dog_*_x
      - sensor.*_dog_*_y
```

## Ontwikkelen

`python3 tests/test_core.py` test de geometrie en het bijhouden van plekken zonder Home Assistant.

Licentie: MIT

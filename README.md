# Brave AudioFocus Build

Patcht Brave Browser fuer Android so dass Videos mit Ton spielen koennen
waehrend Tidal/Spotify gleichzeitig weiterlaeuft.

**Aenderung:** AUDIOFOCUS_GAIN -> AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK

---

## Schritt-fuer-Schritt Anleitung

### 1. Dieses Repository auf GitHub erstellen

1. Gehe zu https://github.com/new
2. Repository Name: `brave-audiofocus-build`
3. Sichtbarkeit: **Private** (empfohlen)
4. Klicke "Create repository"

### 2. Dateien hochladen

Lade alle Dateien aus diesem Ordner in dein neues Repository hoch:
- `.github/workflows/build.yml`  (wichtig: dieser Pfad muss exakt stimmen!)
- `patches/apply_patch.py`
- `README.md`

Am einfachsten per GitHub Web-Interface:
- "Add file" -> "Upload files"
- Achte darauf dass `.github/workflows/build.yml` im richtigen Unterordner landet

### 3. Build starten

1. Gehe zu deinem Repository auf GitHub
2. Klicke auf den Tab "Actions"
3. Klicke auf "Brave Android - AudioFocus Patch Build" in der linken Liste
4. Klicke den Button "Run workflow"
5. Nochmal "Run workflow" bestaetigen

### 4. Warten (~3-6 Stunden)

GitHub baut Brave in der Cloud. Du kannst den Fortschritt live unter
dem "Actions" Tab verfolgen.

### 5. APK herunterladen

Nach erfolgreichem Build:
1. Klicke auf den fertigen Workflow-Run
2. Scrolle nach unten zu "Artifacts"
3. Lade `brave-audiofocus-patched` herunter
4. ZIP entpacken -> APK-Datei

### 6. APK installieren

```
# Brave zuerst deinstallieren (wegen anderem Signatur-Key)
adb install brave-audiofocus-patched.apk
```

Oder: APK-Datei aufs Handy kopieren und dort installieren
(Einstellungen -> "Unbekannte Quellen" muss erlaubt sein)

---

## Hinweise

- GitHub Actions ist fuer Public Repos kostenlos und unbegrenzt
- Fuer Private Repos: 2.000 Minuten/Monat gratis (reicht fuer ~1 Build/Monat)
- Bei jedem Brave-Update: Workflow einfach erneut starten
- Der Build dauert beim ersten Mal laenger (kein Cache)

---

## Falls der Build fehlschlaegt

Haeufige Ursachen:
1. Disk Space zu knapp auf GitHub Runner -> selten, normalerweise 14 GB frei
2. Sync-Fehler -> Workflow nochmal starten
3. Patch nicht angewendet -> Chromium hat Code umstrukturiert, melde dich!

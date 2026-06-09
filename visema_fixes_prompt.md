# Visema — Fix Prompt

Due problemi da risolvere. Leggi tutto prima di scrivere codice.

---

## Problema 1 — GIF overlappate (bug nel worker della queue)

### Causa

In `visema/media/queue.py`, il metodo `_worker` dopo il broadcast non aspetta che la
GIF finisca prima di andare al cooldown. Confronta il comportamento audio vs GIF:

```python
# Comportamento ATTUALE in _worker():
if item_type == "audio":
    await self._wait_for_audio_done()   # ✓ aspetta il completamento
# GIFs auto-complete via CSS timeout in overlay, no ack needed  ← commento SBAGLIATO

await asyncio.sleep(self._cooldown)     # parte subito per le GIF
```

Risultato: se ci sono due GIF in coda, la seconda viene broadcastata mentre la prima
è ancora visibile → si sovrappongono.

### Soluzione

Implementare lo stesso pattern ack usato per l'audio, ma per le GIF.
Il timeout deve essere `display_duration_seconds + fade_out_ms + margine`.

**Nota critica sul timing:** In `overlay.js`, `showGif()` usa questo schema:
- `durationMs` → poi rimuove la classe `.visible` (inizia fade-out)
- +500ms → rimuove l'elemento dal DOM

Quindi il worker deve aspettare almeno `duration + 0.5s` prima che la GIF sia
davvero sparita. Il `gif_done` ack va mandato **dopo** il secondo `setTimeout`
(quando l'elemento viene rimosso dal DOM), non dopo il primo.

### Modifiche richieste

#### `overlay.js` — aggiungere `gif_done` ack

Nella funzione `showGif()`, nel callback del secondo `setTimeout` (quello che
rimuove l'elemento dal DOM), aggiungere l'invio dell'ack **dopo** la rimozione:

```javascript
setTimeout(function () {
    if (img.parentNode) {
        img.parentNode.removeChild(img);
    }
    // NEW: notify queue worker that GIF is fully removed
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ ack: "gif_done" }));
    }
}, 500);
```

**Nota aggiuntiva — disconnessione dell'overlay:** Nella funzione `ws.onclose`,
è già presente `resolveAudioDone()` per sbloccare l'audio pending. Aggiungere
in modo analogo una chiamata a `resolveGifDone()` per sbloccare anche le GIF
pending in caso di disconnessione. La funzione `resolveGifDone()` deve seguire
lo stesso pattern di `resolveAudioDone()`.

#### `queue.py` — aggiungere `_gif_done_event` e `_wait_for_gif_done()`

1. Nella `__init__` di `MediaQueue`, aggiungere accanto a `_audio_done_event`:
   ```python
   self._gif_done_event: Optional[asyncio.Event] = None
   ```

2. Nel metodo `_on_ack`, gestire `"gif_done"` in modo speculare a `"audio_done"`:
   ```python
   async def _on_ack(self, ack_type: str) -> None:
       if ack_type == "audio_done" and self._audio_done_event:
           self._audio_done_event.set()
       elif ack_type == "gif_done" and self._gif_done_event:   # NEW
           self._gif_done_event.set()
   ```

3. Aggiungere il metodo `_wait_for_gif_done()` modellato su `_wait_for_audio_done()`.
   Il timeout deve essere `duration + 1.0` secondi (0.5s fade-out + 0.5s margine).
   Il valore `duration` è nel payload dell'item sotto la chiave `"duration"`.
   Passare `duration` come parametro al metodo (non come costante hardcoded).

4. Nel `_worker`, sostituire il commento `# GIFs auto-complete...` con la chiamata:
   ```python
   if item_type == "audio":
       await self._wait_for_audio_done()
   elif item_type == "gif":                              # NEW
       await self._wait_for_gif_done(
           timeout=item.get("duration", 8) + 1.0
       )
   ```

---

## Problema 2 — Reward creati manualmente: fulfill/cancel non funziona

### Causa

L'API di Twitch permette di aggiornare lo stato di una redemption solo all'app
che ha **creato** il reward tramite API. I reward creati manualmente dal dashboard
Twitch non sono associati a nessuna app, quindi qualsiasi chiamata a
`update_redemption_status()` viene rifiutata con errore (già gestito come warning
in `_fulfill_redemption` e `_cancel_redemption` in `eventsub.py`).

### Soluzione — Opzione A: l'app crea e gestisce i reward via API

L'app deve essere lei a creare i reward tramite `create_custom_reward()`.
I reward creati tramite API sono di proprietà dell'app che li ha creati,
quindi `update_redemption_status()` funzionerà.

**Comportamento richiesto all'avvio:**
- L'app cerca i reward esistenti per nome (come fa già `resolve_reward_ids()`).
- Se un reward **non esiste**: lo crea via API con i parametri da `config.yaml`.
- Se un reward **esiste già ed è stato creato dall'app stessa** (`is_user_input_required`
  e altri campi sono già corretti): lo usa così com'è — **nessuna modifica**.
- Se un reward **esiste ma è stato creato manualmente** (l'app non può gestirlo):
  loggare un warning chiaro che spiega il problema e che il reward deve essere
  eliminato manualmente dal dashboard prima di far girare l'app.

**Come distinguere se un reward è stato creato dall'app:**
Usare il campo `is_enabled` non basta. Il campo affidabile è che se la chiamata
`update_redemption_status()` ritorna `TwitchAPIException` con codice 403 (o il
messaggio contiene "reward not created via API" / "managed reward"), il reward
è manuale. Questo però lo scopri solo al primo fulfill/cancel. Una strategia
più proattiva: tentare immediatamente dopo `resolve_reward_ids()` un
`update_redemption_status()` fittizio su una redemption inesistente — ma questo
è fragile. **La strategia raccomandata:** tracciare in un file locale (es.
`.visema_rewards.json` nella project root, non committato) gli ID dei reward
creati dall'app. All'avvio, se l'ID trovato è in questo file → reward gestibile;
se non è nel file → reward manuale, logga warning.

#### Modifiche richieste in `eventsub.py`

Aggiungere un metodo `ensure_rewards_exist()` nella classe `RedemptionHandler`
(da chiamare in `start_eventsub()` dopo `resolve_reward_ids()`):

```python
async def ensure_rewards_exist(self) -> None:
    """Create rewards via API if they don't exist yet."""
    ...
```

Il metodo deve:

1. Per il reward GIF (`self.reward_gif_name`):
   - Se `self.reward_gif_id` è già settato (reward esiste): verificare se è nel
     registro locale dei reward creati dall'app. Se non lo è, loggare warning e
     procedere senza poter fare fulfill/cancel (comportamento attuale).
   - Se non esiste: crearlo via `broadcaster_client.create_custom_reward()` con:
     - `title`: valore da `config.yaml` (`reward_gif_name`)
     - `cost`: parametro configurabile in `config.yaml` (aggiungere `reward_gif_cost`
       e `reward_sound_cost` alla sezione `twitch:`)
     - `is_user_input_required`: `True`
     - `prompt`: stringa descrittiva (es. `"Incolla il link diretto di una GIF da Giphy"`)
     - `is_enabled`: `True`
   - Salvare l'ID ottenuto nel registro locale.

2. Stesso schema per il reward audio (`self.reward_sound_name`), con:
   - `is_user_input_required`: `True`
   - `prompt`: stringa configurabile (es. `"Scrivi il nome del suono. Usa !soundlist per la lista."`)

3. Il registro locale deve essere un semplice file JSON:
   ```json
   {
     "gif_reward_id": "abc123",
     "sound_reward_id": "def456"
   }
   ```
   Path: `.visema_rewards.json` nella project root (già ignorato da git via `.gitignore`
   — aggiungere se non presente). Caricare all'avvio, salvare dopo ogni creazione.

#### Modifiche richieste in `config.yaml` e `config.py`

Aggiungere sotto la sezione `twitch:`:
```yaml
twitch:
  ...
  reward_gif_cost: 500      # punti canale per il reward GIF
  reward_sound_cost: 300    # punti canale per il reward audio
```

Aggiungere i campi corrispondenti in `TwitchSettings` in `config.py`.

#### Nota sulla gestione dei reward esistenti manuali

Se l'utente ha reward manuali esistenti con gli stessi nomi, il flusso corretto è:

1. L'app trova il reward per nome ma non è nel registro → logga:
   ```
   WARNING: Reward "Mostra una GIF" exists but was not created by this app.
   fulfill/cancel via API will not work. To fix: delete the reward from the
   Twitch dashboard and restart the app — it will be recreated automatically.
   ```
2. Il bot continua a funzionare (enqueue e broadcast funzionano), ma senza
   fulfill/cancel (comportamento attuale già gestito silenziosamente).

Non tentare di eliminare automaticamente reward manuali esistenti — è un'operazione
distruttiva che richiede conferma esplicita dell'utente.

---

## Bug secondario — `audio_playing` ack non gestito (non bloccante)

In `overlay.js`, la funzione `playAudio()` manda `{ ack: "audio_playing" }` al
server (riga 134), ma in `queue.py` il metodo `_on_ack()` gestisce solo
`"audio_done"` e `"gif_done"`. Il `"audio_playing"` arriva in `ws_manager.py`
e viene passato al callback senza effetto — non è un bug bloccante ma genera
rumore nei log se `ws_manager` logga gli ack non riconosciuti.

Se `ws_manager.py` logga un warning per ack sconosciuti, aggiungere `"audio_playing"`
come ack noto e ignorarlo silenziosamente in `_on_ack()`:
```python
elif ack_type == "audio_playing":
    pass  # informational only, no action needed
```

---

## Checklist delle modifiche

| File | Modifica |
|---|---|
| `visema/overlay/overlay.js` | Aggiungere `gif_done` ack dopo rimozione DOM; aggiungere `resolveGifDone()` in `ws.onclose` |
| `visema/media/queue.py` | Aggiungere `_gif_done_event`, `_wait_for_gif_done()`, gestione in `_on_ack` e `_worker` |
| `visema/twitch/eventsub.py` | Aggiungere `ensure_rewards_exist()`, registro `.visema_rewards.json` |
| `config.yaml` | Aggiungere `reward_gif_cost` e `reward_sound_cost` sotto `twitch:` |
| `visema/utils/config.py` | Aggiungere i nuovi campi a `TwitchSettings` |
| `.gitignore` | Aggiungere `.visema_rewards.json` se non presente |

## File da non modificare

- `visema/server/ws_manager.py` — il routing degli ack è già generico, nessuna modifica necessaria
- `visema/server/app.py` — nessuna modifica necessaria
- `visema/main.py` — chiamare `ensure_rewards_exist()` da `start_eventsub()` in `eventsub.py`, non da `main.py`

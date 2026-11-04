# CYBERDECK

L'interfaccia del display **PiSugar Whisplay** di Assistant-PAi: una dashboard **dot-matrix**
minimal a card, con i colori verdi di un vecchio monitor a fosfori.
Sostituisce solo la grafica del [whisplay-ai-chatbot](https://github.com/PiSugar/whisplay-ai-chatbot):
voce, AI, pulsante e batteria funzionano come prima.

![CYBERDECK](anteprime/cyberdeck.png)

*Da sinistra: logo all'accensione, terminale di avvio, pronto, in ascolto, elaborazione, risposta,
spegnimento. Le immagini sono generate dal codice con `deck_preview.py`.*

![Demo animata](anteprime/cyberdeck-demo.gif)

## Cosa fa

### Animazioni che seguono l'assistente
La card **01 AGENT STATUS** mostra una forma fatta di puntini che cambia in base a cosa sta facendo
l'assistente:

| Stato | Titolo | Animazione |
|---|---|---|
| pronto | `READY` | faccina puntinata che "respira" e ogni tanto sbatte gli occhi |
| tieni premuto il tasto e parli | `LISTENING` | forma d'onda animata, con `● REC` che lampeggia |
| trascrizione / elaborazione | `DECODING...` / `THINKING...` | anello puntinato che ruota, con una "cometa" luminosa |
| risposta a voce | `SPEAKING` | barre di puntini che "parlano" |
| errore | `ERROR` | puntini dispersi che tremolano |

Le forme sono fatte degli **stessi 96 puntini**: a ogni cambio di stato i puntini **scivolano**
dalla vecchia forma alla nuova. Così l'onda si trasforma in anello e l'anello nelle barre in modo
fluido. Anche il resto della pagina cambia senza scatti:
- il titolo si "decodifica" lettera per lettera;
- le card si allargano o si restringono con un movimento morbido. Durante la risposta la card del
  testo si ingrandisce.

### Card 02: il terminale
Mostra:
- la tua domanda (`> ...`);
- la risposta, scritta carattere per carattere **in sincronia con la voce**;
- da fermo, l'invito a premere il tasto.

Le immagini generate dall'AI vengono ricostruite a puntini in una card **03 VISION**.

### Accensione
1. Glitch iniziale, poi il logo **CYBERDECK Pi** (o il tuo logo) compare tra i disturbi e sparisce
   con un altro glitch.
2. Righe di codice che scorrono, con dati veri: kernel, rete, batteria, servizi AI.
3. `● SYSTEM STATUS:` / **`ONLINE.`** / tre righe di testo / `[ ENTER TERMINAL ] █`.
4. Un taglio glitch porta alla dashboard, che si accende dall'alto come un tubo catodico.

### Spegnimento
Quando spegni o riavvii il Raspberry (anche dal pannello web o con il tasto della PiSugar):
1. righe di codice di chiusura;
2. `SYSTEM STATUS:` / **`OFFLINE.`** / `[ TERMINAL CLOSED ]`;
3. il logo compare e sparisce con il glitch;
4. lo schermo si spegne come un vecchio CRT: si schiaccia in una riga e poi in un punto.

Accensione e spegnimento hanno anche **effetti sonori** (si possono disattivare).

## Installazione (sul Raspberry Pi)

Prima completa la [GUIDA](../GUIDA.md) fino alla Fase 7 (chatbot funzionante). Poi:

```bash
cd ~
git clone -b claude/raspberry-pi-ai-assistant-vlgr75 https://github.com/retroCyberdan/Assistant-PAi.git
bash ~/Assistant-PAi/cyberdeck/install.sh
```

Se il repository è già sul Raspberry, aggiornalo invece di clonarlo:
`cd ~/Assistant-PAi && git pull && bash cyberdeck/install.sh`.

Lo script:
1. salva l'interfaccia originale in `python/chatbot-ui.original.py`;
2. **rimuove le versioni precedenti** (interfacce Videotex / cyberpunk e il vecchio pannello);
3. copia i file `deck_*.py` in `whisplay-ai-chatbot/python/` e installa un piccolo lanciatore al posto
   di `chatbot-ui.py`;
4. **pulisce il file `.env`** dalle vecchie voci `VTX_*` (copia di sicurezza in `.env.bak`). Le chiavi
   API non vengono toccate;
5. installa il **pannello web**: chiede la password (o mantiene quella che avevi) e crea il servizio
   `cyberdeck-panel`;
6. riavvia l'assistente.

Non serve ricompilare (`build.sh`): CYBERDECK è solo Python e usa librerie già installate dal chatbot
(Pillow, numpy, Flask).

**Per tornare all'interfaccia originale** hai due strade:
- dal pannello web scegli *Interfaccia → Originale PiSugar*;
- oppure esegui `bash ~/Assistant-PAi/cyberdeck/uninstall.sh`.

**Per aggiornare il chatbot** (`git pull` nella cartella `whisplay-ai-chatbot`):
1. esegui prima `uninstall.sh`;
2. fai `git pull` e `bash build.sh`;
3. esegui di nuovo `install.sh`.

## Pannello web

Dal browser di un telefono o di un PC sulla stessa rete Wi-Fi: **`http://pai.local:8080`** (oppure
`http://<indirizzo-IP>:8080`).

Dal pannello puoi:
- **caricare il tuo logo** (PNG/JPG). Viene ricostruito a puntini e mostrato all'accensione e allo
  spegnimento al posto della scritta;
- cambiare **nome** (es. `CYBERDECK Pi`: la prima parola va in grande, il resto sotto in evidenza);
- scegliere i **colori**: verde fosforo, ambra o ghiaccio;
- modificare i **testi**: frase della pagina iniziale, righe di accensione e spegnimento, prompt finale;
- regolare gli **effetti**: animazioni di accensione e spegnimento (completa / rapida / nessuna), suoni,
  glitch a riposo, effetto CRT, velocità del testo;
- vedere l'**anteprima del display** prima di salvare;
- **salvare e riavviare** l'assistente, **riavviare** o **spegnere** il Raspberry;
- cambiare la password.

Sicurezza:
- accesso con password; dopo 5 tentativi sbagliati l'accesso si blocca per un minuto;
- i moduli sono protetti contro le richieste falsificate (CSRF);
- il pannello modifica solo le voci `UI_STYLE` e `DECK_*` del `.env`, sempre con una copia `.env.bak`;
- usa un permesso `sudo` limitato a tre comandi: riavviare l'assistente, riavviare e spegnere il
  Raspberry.

Il pannello usa HTTP semplice: usalo **solo sulla rete di casa**.

Password dimenticata? Dal Raspberry: `python3 ~/whisplay-ai-chatbot/python/deck_panel.py --set-password`.

## Impostazioni (file `~/whisplay-ai-chatbot/.env`)

Si cambiano dal pannello web; a mano funzionano così:

```ini
UI_STYLE=cyberdeck
DECK_NAME=CYBERDECK Pi
DECK_PALETTE=verde
DECK_HINT=Tieni premuto il tasto e parla
DECK_BOOT=full
DECK_SHUTDOWN=full
DECK_BOOT_LINES=The Simulation has been mapped.|The Archives are open.|Observer protocol initiated.
DECK_SHUTDOWN_LINES=The Simulation has been archived.|The Archives are sealed.|Observer protocol terminated.
DECK_ENTER_TEXT=[ ENTER TERMINAL ]
DECK_SOUND=1
DECK_CRT=0.7
DECK_GLITCH=0.2
DECK_TEXT_SPEED=60
```

Note sulle voci:
- `UI_STYLE`: `cyberdeck` oppure `original`;
- `DECK_PALETTE`: `verde`, `ambra` oppure `ghiaccio`;
- `DECK_BOOT` e `DECK_SHUTDOWN`: `full`, `quick` oppure `off`;
- `DECK_CRT` e `DECK_GLITCH`: da 0 a 1;
- `DECK_TEXT_SPEED`: caratteri al secondo.

Altre voci:
- `DECK_LOGO_IMAGE=/percorso/logo.png` usa un logo personalizzato (il pannello lo salva in
  `~/.config/cyberdeck/logo.png`);
- `DECK_AUDIO_DEVICE` serve solo se i suoni escono dal dispositivo sbagliato.

Dopo una modifica a mano: `sudo systemctl restart chatbot.service`.

## Provarlo sul PC (senza Raspberry)

```bash
pip install pillow numpy
python3 deck_preview.py demo anteprime          # sessione completa: GIF + immagini
python3 deck_preview.py snapshot prova.png      # pagina iniziale + risposta
DECK_PALETTE=ambra DECK_NAME="NEURODECK X" python3 deck_preview.py snapshot prova.png
```

## Come funziona

Il chatbot originale ha due processi:
- **Node.js** gestisce microfono, AI e voce;
- **Python** disegna sul display.

I due comunicano con messaggi JSON su `localhost:12345`. `deck_ui.py` parla lo stesso protocollo,
quindi il resto del chatbot non va modificato.

Quando il sistema si spegne, `systemd` invia all'interfaccia il segnale di arresto: CYBERDECK lo
intercetta, mostra l'animazione di spegnimento e poi esce.

| File | Contenuto |
|---|---|
| `deck_ui.py` | protocollo socket, dashboard, transizioni, accensione e spegnimento, suoni |
| `deck_gfx.py` | font dot-matrix, card, forme a puntini e morph, immagini a puntini, glitch, CRT |
| `deck_font.py` | font bitmap 5x7 originale con lettere accentate italiane |
| `deck_panel.py` | pannello web (Flask) |
| `deck_preview.py` | anteprime e demo animata senza hardware |
| `install.sh` / `uninstall.sh` | installazione, migrazione dalle versioni precedenti, ripristino |

File creati sul Raspberry:
- `~/whisplay-ai-chatbot/python/deck_*.py`, cioè i moduli;
- `~/.config/cyberdeck/`, con password del pannello e logo;
- i servizi `cyberdeck-panel.service` e `/etc/sudoers.d/cyberdeck`.

Se avevi usato le vecchie interfacce, il logo caricato allora è rimasto in `~/pai-assets/`: se non
ti serve più, puoi cancellare la cartella con `rm -r ~/pai-assets`.

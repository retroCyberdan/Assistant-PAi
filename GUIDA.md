# Assistant-PAi: guida passo passo

In questa guida costruiamo un assistente vocale AI portatile con:

| Componente | Funzione |
|---|---|
| **Raspberry Pi 4 Model B** (2 GB o più) oppure **Raspberry Pi 5** (4 GB o più) | il "cervello" |
| **PiSugar Whisplay HAT** | display LCD, microfoni, altoparlante, pulsante e LED RGB (codec audio WM8960) |
| **PiSugar 3 Plus 5000 mAh** | batteria, RTC e gestione dell'alimentazione |
| microSD da 16 GB o più (classe A1/A2) | sistema operativo |
| Alimentatore USB-C 5 V / 3 A | per ricaricare la PiSugar |

Il software è il progetto ufficiale **[whisplay-ai-chatbot](https://github.com/PiSugar/whisplay-ai-chatbot)**,
lo stesso dei tutorial del canale YouTube PiSugar Studio. Funziona così:

```
[tieni premuto il pulsante] → microfono → ASR (voce→testo) → LLM (risposta) → TTS (testo→voce) → altoparlante
                                                        └→ testo ed emoji sul display
```

> Nota: il README ufficiale cita come schede di riferimento il Pi Zero 2 W e il Pi 5. Il driver Whisplay però
> supporta "tutti i modelli con header a 40 pin", quindi anche il Pi 4. Il Pi 4 è molto più veloce del Zero 2 W
> e con i servizi cloud va benissimo.

### Pi 4 o Pi 5?

Entrambi funzionano con questa guida, e tutti i passaggi sono identici. Il Pi 5 offre:
- **più velocità:** risposte e animazioni del display più fluide;
- **compatibilità con la batteria:** il README ufficiale indica proprio la PiSugar 3 Plus da 5000 mAh
  come versione per il Pi 5;
- **stesso header a 40 pin:** Whisplay e PiSugar si montano allo stesso modo.

Quanta RAM serve:
- **4 GB bastano** con i servizi cloud (OpenAI, Anthropic, Gemini), cioè la configurazione di questa guida;
- **8 GB sono consigliati** dal README ufficiale se vuoi far girare l'AI in locale, senza Internet
  (Ollama, Whisper locale: Fase 9).

Attenzione al **raffreddamento**: il Pi 5 scalda più del Pi 4, e il Whisplay copre la zona del processore,
dove andrebbe la ventola ufficiale (Active Cooler). Prima di acquistarla, misura lo spazio tra il Pi e il
Whisplay. Le alternative sono:
- un **dissipatore passivo basso**;
- un **GPIO stacking header** (prolunga a 40 pin) per alzare il Whisplay e fare spazio alla ventola.

Se passi da un Pi 4 già configurato a un Pi 5, segui la sezione
[Passare dal Pi 4 al Pi 5](#passare-dal-pi-4-al-pi-5).

---

## Fase 1: montaggio hardware

1. **Spegni tutto.** Non montare né smontare niente mentre la batteria è accesa.
2. **Monta la PiSugar 3 Plus SOTTO il Raspberry Pi.**
   - La PiSugar 3 Plus si collega con dei **pin a molla (pogo pin)** che toccano da sotto i pin del GPIO
     (5 V, GND, SDA, SCL). Non occupa l'header e lascia libero il lato superiore per il Whisplay.
   - Fissala con le viti e i distanziali in dotazione nei 4 fori del Pi. Controlla che i pogo pin
     siano allineati e premano sulle saldature dei pin 1–6 del GPIO.
   - Collega il connettore della batteria alla scheda PiSugar, se non è già collegato.
3. **Inserisci il Whisplay HAT SOPRA, sull'header GPIO a 40 pin.**
   - Il Whisplay ha il formato del Pi Zero, quindi sul Pi 4 e sul Pi 5 copre solo una parte della scheda.
     Allinea il **pin 1** del connettore femmina del Whisplay con il pin 1 del Pi (l'angolo vicino al
     foro di montaggio, lato slot microSD) e premi in modo uniforme fino in fondo.
   - Se vuoi più spazio o una ventola, usa un **GPIO stacking header** (prolunga) di 40 pin.
4. **Non ci sono conflitti tra le due schede.** Condividono il bus I2C ma usano indirizzi diversi
   (PiSugar: 0x57 e 0x68; codec WM8960: 0x1a).
5. **Ricarica e accensione.** Ricarica sempre dalla porta **USB-C della PiSugar**, non da quella del Pi.
   Per accendere o spegnere premi il pulsante della PiSugar (di solito un tocco breve seguito da una
   pressione lunga; controlla la documentazione della tua revisione: <https://docs.pisugar.com>).

> Consiglio: il Pi scalda, il Pi 5 più del Pi 4. Un dissipatore sul processore aiuta, soprattutto dentro
> un case (sul Pi 5 vedi la nota sul raffreddamento in apertura).

---

## Fase 2: installare il sistema operativo

1. Sul PC scarica **Raspberry Pi Imager**: <https://www.raspberrypi.com/software/>
2. Scegli il dispositivo (**Raspberry Pi 4** o **Raspberry Pi 5**) e il sistema **Raspberry Pi OS (64-bit)**, completo o Lite
   (Bookworm o più recente). Il repo Whisplay consiglia la versione ufficiale completa; la Lite va bene
   se usi il Pi solo in modalità headless.
3. In **"Modifica impostazioni"** (icona ingranaggio) imposta:
   - hostname, ad esempio `pai`
   - utente e password (ad esempio utente `pi`)
   - Wi-Fi (SSID, password, paese `IT`)
   - **abilita SSH**
   - fuso orario `Europe/Rome`, tastiera `it`
4. Scrivi la microSD, inseriscila nel Pi e accendi con il pulsante della PiSugar.
5. Dal PC collegati via SSH:
   ```bash
   ssh pi@pai.local
   ```
6. Aggiorna il sistema:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo apt install -y git
   sudo reboot
   ```

---

## Fase 3: driver del Whisplay HAT (audio, display, pulsante)

```bash
cd ~
git clone https://github.com/PiSugar/Whisplay.git --depth 1
cd Whisplay
sudo bash install_driver.sh
sudo reboot
```

Lo script abilita I2C, I2S e SPI e installa il driver della scheda audio (WM8960 o ES8389, secondo la
revisione del tuo HAT).

**Verifica dopo il riavvio:**

```bash
aplay -l       # deve comparire la scheda audio del Whisplay (es. "whisplaysound" / "wm8960")
arecord -l     # deve comparire il microfono

# test microfono + altoparlante: registra 5 secondi e riproduci
arecord -D plughw:CARD=whisplaysound -f S16_LE -r 16000 -c 2 -d 5 test.wav
aplay   -D plughw:CARD=whisplaysound test.wav
```

> Se il nome della scheda è diverso, usa quello mostrato da `aplay -l` (oppure `plughw:1,0`).
> Se il volume è basso, regolalo con `alsamixer` (F6 per scegliere la scheda Whisplay).

Nella cartella `~/Whisplay/example` trovi delle demo per provare il display e il pulsante.

---

## Fase 4: software della batteria PiSugar 3 Plus

```bash
cd ~
wget https://cdn.pisugar.com/release/pisugar-power-manager.sh
bash pisugar-power-manager.sh -c release
```

Durante l'installazione scegli il modello **PiSugar 3** (la versione Plus usa lo stesso software).

Al termine:
- l'interfaccia web è su `http://pai.local:8421`: livello batteria, sincronizzazione dell'RTC,
  **spegnimento sicuro a batteria scarica**, pulsante personalizzabile, accensione programmata;
- il servizio `pisugar-server` ascolta anche sulla porta TCP **8423**. Il chatbot la usa per mostrare
  la percentuale della batteria sul display.

Verifica:

```bash
sudo i2cdetect -y 1                       # devono comparire 57 e 68 (PiSugar) e 1a (codec audio)
echo "get battery" | nc -q 1 127.0.0.1 8423
```

> Consiglio: nella web UI imposta lo spegnimento sicuro al 5–10% di batteria, così la microSD non si
> corrompe quando la batteria si scarica.

---

## Fase 5: installare il chatbot AI

```bash
cd ~
git clone https://github.com/PiSugar/whisplay-ai-chatbot.git
cd whisplay-ai-chatbot
bash install_dependencies.sh     # Node.js 20, sox, ffmpeg, librerie Python, font ed emoji
source ~/.bashrc
```

Ci vogliono alcuni minuti.

---

## Fase 6: scegliere i "cervelli" (ASR, LLM e TTS) e configurare `.env`

Il chatbot è modulare: in `.env` scegli quale servizio usare per ognuna delle tre fasi.

| Fase | Opzioni principali | Consiglio per l'italiano |
|---|---|---|
| `ASR_SERVER` (voce→testo) | `openai`, `gemini`, `whisper`, `faster-whisper`, `vosk`, `tencent`, `volcengine`, `aws` | `openai` (Whisper, riconosce l'italiano in automatico) oppure `gemini` |
| `LLM_SERVER` (risposta) | `openai`, `gemini`, `anthropic`, `grok`, `ollama`, `openrouter`, `perplexity`, `qwen`, … | `openai`, `gemini` o `anthropic` (Claude) |
| `TTS_SERVER` (testo→voce) | `openai`, `gemini`, `piper`, `espeak-ng`, `tencent`, `volcengine`, `aws` | `openai` (la voce `nova` parla bene in italiano) |

Crea la configurazione:

```bash
whisplay configure        # procedura guidata, in alternativa: cp .env.template .env
nano .env
```

Nel repo trovi un esempio già pronto per l'italiano: **[`config/env.esempio-italiano`](config/env.esempio-italiano)**.
Contiene tre profili (solo OpenAI; OpenAI + Claude; solo Gemini). Copia le righe del profilo che preferisci
in `~/whisplay-ai-chatbot/.env` e inserisci la tua chiave API.

Dove ottenere le chiavi API:
- OpenAI: <https://platform.openai.com/api-keys>
- Anthropic (Claude): <https://console.anthropic.com/>
- Google Gemini: <https://aistudio.google.com/apikey>

> **Sicurezza:** non caricare mai il file `.env` con le chiavi su GitHub. In questo repo `.env` è già
> escluso da `.gitignore`.

---

## Fase 7: compilare e provare

```bash
cd ~/whisplay-ai-chatbot
bash build.sh
bash run_chatbot.sh
```

**Come si usa:**
- **tieni premuto il pulsante** del Whisplay e parla;
- **rilascia**: il display mostra la trascrizione, poi la risposta, e l'assistente risponde a voce;
- il LED RGB e le emoji sul display indicano lo stato (in ascolto, sto pensando, sto parlando);
- doppio clic a riposo: modalità fotocamera, solo se hai una Pi Camera e `ENABLE_CAMERA=true`.

Interrompi con `Ctrl+C`.

---

## Fase 8: avvio automatico all'accensione

```bash
cd ~/whisplay-ai-chatbot
bash startup.sh
```

Lo script crea un servizio di sistema (`chatbot.service`) e imposta il Pi in modalità senza desktop.
Da quel momento basta premere il pulsante della PiSugar: dopo circa 30–60 secondi l'assistente è pronto.

Comandi utili:

```bash
tail -f ~/whisplay-ai-chatbot/chatbot.log      # log in tempo reale
sudo systemctl restart chatbot.service         # dopo aver modificato .env
sudo systemctl status chatbot.service
```

Per aggiornare:

```bash
cd ~/whisplay-ai-chatbot
git pull
bash upgrade-env.sh          # aggiunge al tuo .env le nuove opzioni
bash build.sh
sudo systemctl restart chatbot.service
```

---

## Fase 9 (opzionale): funzioni extra

Tutte si attivano da `.env`; i dettagli sono nella [wiki ufficiale](https://github.com/PiSugar/whisplay-ai-chatbot/wiki).

- **Parola di attivazione (mani libere):** `WAKE_WORD_ENABLED=true`, `WAKE_WORDS=hey_jarvis`
  (richiede openwakeword ≥ 0.6.0).
- **Personalità:** `SYSTEM_PROMPT="..."` (vedi l'esempio in italiano).
- **Memoria della conversazione:** `CHAT_HISTORY_RESET_TIME=300` (in secondi).
- **Fotocamera e visione:** `ENABLE_CAMERA=true`, `USE_CAPTURED_IMAGE_IN_CHAT=true`.
- **Generazione di immagini** mostrate sul display: `IMAGE_GENERATION_SERVER=openai` o `gemini`.
- **Base di conoscenza (RAG)** con i tuoi documenti: `ENABLE_RAG=true` (richiede Ollama e Qdrant).
- **Funzionamento offline:** `ASR_SERVER=vosk` o `faster-whisper`, `LLM_SERVER=ollama`
  (con un modello piccolo, ad esempio `qwen2.5:0.5b` o `gemma3:1b`) e `TTS_SERVER=piper`
  (con una voce italiana, ad esempio `it_IT-paola-medium`). Sul Pi 4 funziona ma è lento: serve
  almeno 4 GB di RAM, meglio 8.

---

## Fase 10 (opzionale): interfaccia CYBERDECK ROCKY Pi

Questa fase trasforma il display in **CYBERDECK ROCKY Pi v1.0** (サイバーデッキ ロッキー パイ), una dashboard
a puntini (dot-matrix) con i colori verdi di un vecchio monitor a fosfori:
- **Rocky**, un Jack Russell in pixel art, vive sullo schermo: mentre aspetta si siede, tira fuori la
  lingua, fa un giro o schiaccia un pisolino; mentre l'assistente elabora scava, salta o si rotola;
- **animazioni che cambiano in base a cosa fa l'assistente:** Rocky si scioglie in un'onda mentre
  parli, e torna Rocky mentre elabora; poi barre che "parlano" mentre risponde, con passaggi fluidi;
- **katakana** sotto il nome, sotto gli stati e accanto alle etichette;
- **accensione e spegnimento animati:** logo con glitch, righe di codice che scorrono e
  `SYSTEM STATUS: ONLINE` / `OFFLINE`;
- **pannello web** `http://pai.local:8080` per cambiare logo, nome, colori e testi dal telefono.

**Prima installazione:**

```bash
cd ~ && git clone -b claude/raspberry-pi-ai-assistant-vlgr75 https://github.com/retroCyberdan/Assistant-PAi.git
bash ~/Assistant-PAi/cyberdeck/install.sh
```

**Aggiornamento** (anche se avevi installato le vecchie interfacce Videotex / cyberpunk: lo script le
rimuove e ripulisce il `.env` da solo):

```bash
cd ~/Assistant-PAi && git pull
bash cyberdeck/install.sh
```

Istruzioni complete in **[cyberdeck/README.md](cyberdeck/README.md)**.

---

## Passare dal Pi 4 al Pi 5

Conviene installare tutto da zero su una **nuova microSD**: si fa in fretta e si evitano problemi.
La microSD del Pi 4 resta intatta come copia di sicurezza.

1. **Salva le tue impostazioni dal Pi 4.** Dal PC, con WinSCP / Cyberduck / FileZilla (connessione SFTP
   a `pai.local`) oppure con questi comandi:
   ```bash
   mkdir -p backup-pai
   scp pi@pai.local:~/whisplay-ai-chatbot/.env backup-pai/
   scp -r pi@pai.local:~/.config/cyberdeck backup-pai/   # logo e password del pannello web
   ```
   Il file `.env` contiene le tue **chiavi API**: tienilo al sicuro e non caricarlo su GitHub.
2. **Spegni e smonta** batteria e Whisplay dal Pi 4. Rimontali sul Pi 5 come nella Fase 1.
3. **Prepara una nuova microSD** (Fase 2), scegliendo **Raspberry Pi 5** in Raspberry Pi Imager. Usa lo
   stesso hostname (`pai`) e lo stesso utente (`pi`), così indirizzi e percorsi non cambiano.
4. **Ripeti le Fasi 3, 4 e 5:** driver Whisplay, software della batteria, installazione del chatbot.
5. **Rimetti le tue impostazioni** sul Pi 5:
   ```bash
   scp backup-pai/.env pi@pai.local:~/whisplay-ai-chatbot/.env
   ssh pi@pai.local "mkdir -p ~/.config"
   scp -r backup-pai/cyberdeck pi@pai.local:~/.config/
   ```
   Non serve rifare la Fase 6: le scelte di ASR, LLM e TTS e le chiavi API sono già nel `.env`.
6. **Completa le Fasi 7 e 8** (compilazione e avvio automatico). Se usi CYBERDECK, ripeti anche la
   Fase 10. `install.sh` non chiederà una nuova password del pannello, perché trova già quella copiata.

Se ricevi avvisi di alimentazione insufficiente sul Pi 5 (ad esempio nel log `dmesg`), verifica la carica
della batteria e consulta la documentazione PiSugar per il Pi 5: <https://docs.pisugar.com>.

---

## Risoluzione dei problemi

| Problema | Soluzione |
|---|---|
| `aplay -l` non mostra il Whisplay | Controlla che l'HAT sia inserito bene, rilancia `sudo bash install_driver.sh` e riavvia. Controlla `/boot/firmware/config.txt`. |
| Display nero | SPI non attivo: `sudo raspi-config nonint do_spi 0` e riavvio. |
| Audio distorto o troppo basso | `alsamixer` oppure `INITIAL_VOLUME_PERCENT=70` in `.env`. |
| L'assistente non capisce l'italiano | Usa `ASR_SERVER=openai` o `gemini`; se usi `whisper` locale imposta `WHISPER_LANGUAGE=Italian`. |
| La risposta è in inglese | Aggiungi al `SYSTEM_PROMPT` "Rispondi sempre in italiano". |
| Nessuna percentuale della batteria | `sudo systemctl status pisugar-server`; deve rispondere sulla porta 8423. |
| Il Pi si riavvia sotto carico | Batteria quasi scarica o pogo pin che toccano male: ricarica e ricontrolla il montaggio. |
| Errore 401/403 nei log | Chiave API errata o senza credito. |

---

## Risorse

- Driver Whisplay HAT: <https://github.com/PiSugar/Whisplay>
- Chatbot AI: <https://github.com/PiSugar/whisplay-ai-chatbot> (immagini pronte nella wiki)
- Documentazione PiSugar: <https://docs.pisugar.com>
- Tutorial video: canale YouTube PiSugar Studio, <https://www.youtube.com/@PiSugarStudio>

# ai-chat-app
Applikationen udstiller et webbasseret chat-interface til afvikling af samtaler med AI-assistenter via Azure OpenAI API-endpoints. Samtaler opbevares i Postgres database. 

Løsningen kan fungere som chatvindue i [ai-chat-portal](https://github.com/Randers-Kommune-Digitalisering/ai-chat-portal) - en chatportal til udstilling af forskellige assistenter med brugerstyret samtalehistorik. 

## Features

#### :robot: Chat med AI assistenter fra Azure (enten chat-completion assistenter eller agenter)
Backend vælger mellem chat- og agent-flow via `ASSISTANT_TYPE` og tilbyder endpoints som `POST /api/chat/messages` og `POST /api/threads/<thread_id>/messages`.

#### :paperclip: Upload af filer i samtaler
Frontend sender filer som base64 i request-body, backend dekoder til bytes og gemmer dem som attachments på beskeder, så konteksten kan genbruges ved fortsat chat.

#### :elephant: Opbevaring af samtaler i Postgres
Samtaler og beskeder persistéres i Postgres (Conversation/Message/Attachment/Reference) og opdateres løbende, når der sendes nye bruger- og assistentbeskeder.

#### :closed_lock_with_key: Indlæsning af samtaler med nødvendige rettigheder
Samtaler kan kun indlæses via en kortlivet, signeret “load permit” (RS256) gennem `POST /api/conversations/load` (legacy `GET /api/conversations/<id>` er deaktiveret).

#### :shield: Sikker tovejskommunikation med [ai-chat-portal](https://github.com/Randers-Kommune-Digitalisering/ai-chat-portal) (til samtalehistorik)
Portalen kan indlæse samtaler ved at udstede et permit, som app’en validerer, og frontend kan sende/rydde samtaler samt synkronisere state via portal messaging. Læs mere om [sikret indlæsning af samtaler her](https://github.com/Randers-Kommune-Digitalisering/ai-chat-portal/blob/development/README.md#sikret-indl%C3%A6sning-af-samtaler-portal--indlejret-chat-app).

#### :label: Generering af samtaletitler
Samtaler der lagres i Postgres-database bliver automatisk tildelt en beskrivende titel, genereret af separat AI-model.

#### :warning: CPR-filtrering til at opfange følsomme oplysninger inden afsendelse
Backend matcher CPR-numre med regex og kan returnere fund via `POST /api/filter`, så klienten kan advare/handle før afsendelse.

#### :lock: Anonymisering af følsomme oplysninger

Før beskeder sendes til Azure, bliver følsomt indhold redigeret ud (fx CPR) ved at erstatte fund med placeholders som `[REDACTED #1]`.

#### :twisted_rightwards_arrows: Alternativ assistent toggle

Der kan udstilles to forskellige assistenter i samme chatvindue med en visuel toggle til at skifte mellem disse. Brugere kan med denne feature skifte mellem de to assistenter i løbet af en samtale.

#### :wrench: Fejlhåndtering

Robust håndtering af Azure/OpenAI-fejl som en del af chat-flowet:
* Automatiske retries på transiente fejl (fx timeout/5xx/429) med backoff.
* Konsistente API-fejl (stabile HTTP status-koder) og server-side logging til fejlsøgning.
* Agent-flow beskytter mod dubletter og håndterer “run already in progress” scenarier.


## Miljøvariabler
Applikationen er afhængig af en række miljøvariabler. De nødvendige miljøvariabler afhænger af assistentens type, `ASSISTANT_TYPE`.

### Nødvendige miljøvariabler
Disse skal altid være sat (uanset assistent-type), da de bruges uden sikre defaults.

| Navn | Default | Beskrivelse |
|---|---:|---|
| `ASSISTANT_TYPE` | `Chat` | Vælger kørselstype: `Agent`/`Assistant` eller `Chat`. |
| `ASSISTANT_NAME` | `AI Assistent` | Visningsnavn i UI. |
| `ASSISTANT_NAME_ID` | `default-assistant` | ID som portalen bruger til at identificere assistenten. |
| `PREDEFINED_QUESTIONS` | — | Semikolon-separeret liste af forslagsspørgsmål (fx `Spg1;Spg2`). |
| `AZURE_OPENAI_KEY` | — | API-nøgle til Azure OpenAI. |
| `AZURE_OPENAI_ENDPOINT` | — | Base endpoint for Azure OpenAI-ressourcen. |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | — | Deployment/model-navn der bruges til chat. |
| `AZURE_API_VERSION_OPENAI` | `2024-12-01-preview` | API-version for OpenAI endpoints. |
| `FEEDBACK_MAIL_API_URL` | — | Endpoint til feedback-mail service. |
| `FEEDBACK_MAIL_API_RECIPIENT` | — | Modtageradresse for feedback. |
| `FEEDBACK_MAIL_API_SENDER` | — | Afsenderadresse for feedback. |

### Chat-type miljøvariabler
Skal sættes når `ASSISTANT_TYPE` er `Chat`.

| Navn | Default | Beskrivelse |
|---|---:|---|
| `SYSTEM_PROMPT` | `Du er en hjælpsom AI-assistent.` | System prompt for chat. |
| `USE_GENERAL_KNOWLEDGE` | `True` | Om assistenten må bruge generel viden ud over kilder/dokumenter. |
| `EMPHASIZE_RECENT_CONTENT` | `True` | Om nyligt indhold vægtes højere i prompt-kontekst. |
| `TOP_P_VALUE` | `0.8` | Sampling-parameter (top-p). |
| `TEMPERATURE_VALUE` | `0.2` | Sampling-parameter (temperature). |

### Agent-type miljøvariabler
Skal sættes når `ASSISTANT_TYPE` er `Agent`.

| Navn | Default | Beskrivelse |
|---|---:|---|
| `ASSISTANT_ID` | — | Azure agent-id. |
| `AZURE_AIFOUNDRY_PROJECT_NAME` | — | Project-navn til Azure AI Foundry. |

### Valgfrie miljøvariabler

| Navn | Default | Beskrivelse |
|---|---:|---|
| `ASSISTANT_ALT_ID` | — | Sekundær assistant-id til assistent-toggle (sætter `SHOW_ASSISTANT_TOGGLE`), hvis `ASSISTANT_TYPE` er `agent`. |
| `ALT_TOGGLE_LABEL` | `Brug alternativ assistent` | Label for alternativ assistent-toggle i UI, hvis `ASSISTANT_ALT_ID` er sat. |
| `ALT_ALERT_MSG` | — | Alert-tekst der kan vises ifm. alternativ assistent, hvis `ASSISTANT_ALT_ID` er sat. |
| `ALT_ALERT_TYPE` | `info` | Alert-type for alternativ assistent (`info`, `warning`, `danger`), hvis `ALT_ALERT_MSG` er sat. |
| `ALLOW_FILE_UPLOAD` | `False` | Slår fil-upload til/fra. |
| `AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION` | — | Alias: `AZURE_OPENAI_DEPLOYMENT_NAME`. Deployment/model-navn til automatisk titelgenerering. |
| `AZURE_AISEARCH_INDEX_NAME` | — | Index-navn i Azure AI Search (hvis retrieval anvendes), kan kun anvendes hvis `ASSISTANT_TYPE` er `chat`. |
| `AZURE_AISEARCH_ENDPOINT` | — | Endpoint for Azure AI Search, hvis `AZURE_AISEARCH_INDEX_NAME` er sat. |
| `AZURE_AISEARCH_SEMANTIC_CONFIG` | `default-semantic-config` | Navn på semantic configuration i Azure AI Search, hvis `AZURE_AISEARCH_INDEX_NAME` er sat. |
| `AZURE_API_VERSION_FILES` | `2024-10-21` | API-version for file endpoints, hvis `AZURE_AISEARCH_INDEX_NAME` er sat. |
| `TOP_N_DOCUMENTS` | `10` | Antal dokumenter der hentes fra search/retrieval, hvis `AZURE_AISEARCH_INDEX_NAME` er sat. |
| `SEARCH_STRICTNESS` | `3` | Stramhed for søgning/retrieval, hvis `AZURE_AISEARCH_INDEX_NAME` er sat. |
| `POSTGRES_USER` | — | Postgres brugernavn (skal sættes for at DB er aktiv). |
| `POSTGRES_PASSWORD` | — | Postgres password (skal sættes for at DB er aktiv). |
| `POSTGRES_HOST` | — | Postgres host (skal sættes for at DB er aktiv). |
| `POSTGRES_PORT` | `5432` | Postgres port. |
| `POSTGRES_DB` | — | Postgres databasenavn (skal sættes for at DB er aktiv). |
| `CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM` | — | RS256 public key (PEM) til validering af portalens load-permits. |
| `CONVERSATION_LOAD_PERMIT_ISSUER` | `gpt-dashboard-portal` | Forventet JWT issuer for load-permit. |
| `CONVERSATION_LOAD_PERMIT_AUDIENCE` | `chat-app` | Forventet JWT audience for load-permit. |
| `CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS` | — | Komma-separeret liste af tilladte `kid` værdier fra JWT header. |
| `CSP_FRAME_ANCESTORS` | — | Hvis sat, begrænser hvem der må embedde app’en (CSP `frame-ancestors`). |
| `DEBUG` | `False` | Aktiverer debug-funktionalitet i backend. |
| `PORT` | `8080` | Port som backend skal lytte på. |
| `POD_NAME` | `pod_name_not_set` | Instance-navn (bruges bl.a. til metrik-labels). |
| `METRICS_APP` | `ai-chat-app` | Prometheus label: applikationsnavn. |
| `METRICS_DEPLOYMENT` | `unknown` | Alias: `DEPLOYMENT`. Prometheus label: deployment-miljø/navn. |
| `METRICS_INSTANCE` | `POD_NAME` | Prometheus label: instans (typisk pod/container). |

## Metrics
Brugsstatistik trackes og udstilles med følgende Prometheus-metrikker på `/metrics`:

* `chat_messages_total{app, deployment, instance, mode}`
	* Tæller antal bruger-beskeder modtaget af backend.
	* `mode` er `chat` eller `agent`.

* `chat_conversations_total{app, deployment, instance, mode}`
	* Tæller antal samtaler oprettet i backend.
	* `mode` er `chat` eller `agent`.

* `chat_feedback_total{app, deployment, instance, feedback_type}`
	* Tæller feedback events.
	* `feedback_type` er `like` (thumbs up) eller `custom` (tekstfeedback sendt).

Metrikkerne er afhængige af følgende miljøvariabler:

| Navn | Default | Beskrivelse |
|---|---:|---|
| `METRICS_APP` | `ai-chat-app` | Prometheus label: applikationsnavn. |
| `METRICS_DEPLOYMENT` | `unknown` | Alias: `DEPLOYMENT`. Prometheus label: deployment-miljø/navn. |
| `METRICS_INSTANCE` | — | Alias: `POD_NAME`. |

## Udvikling

* Kørsel af Frontenden (Vue): ```cd vue && npm install && npm run dev```
* Kørsel af Bakcenden (Python): ```python flask/src/main.py```
* Kørsel af frontend + backend i docker: ```docker-compose up``` i top dir (backend på port 8080, frontend på port 3000)
* Bygge docker image: ```docker build -t ai-chat-app .```
* Kør container ud fra det image man byggede: ```docker run -p 8080:8080 ai-chat-app```
* Lint: ```flake8 python/src tests --count --ignore=E501,W503 --show-source --statistics```
* Unit tests: ``` pytest ```

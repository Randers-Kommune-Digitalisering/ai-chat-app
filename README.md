# TODO: README er ikke blevet updated i 2 måneder
# TODO: Beskriv flowet med Azure fejl håndtering
# ai-chat-app
Applikationen udstiller et webbasseret chat-interface til afvikling af samtaler med AI-assistenter via Azure OpenAI API-endpoints. Samtaler opbevares i Postgres database. 

Løsningen kan fungere som chatvindue i [ai-chat-portal](https://github.com/Randers-Kommune-Digitalisering/ai-chat-portal) - en chatportal til udstilling af forskellige assistenter med brugerstyret samtalehistorik. 

## Features

#### - Chat med AI assistenter fra Azure (enten chat-completion assistenter eller agenter)
Backend vælger mellem chat- og agent-flow via `ASSISTANT_TYPE` og tilbyder endpoints som `POST /api/chat/messages` og `POST /api/threads/<thread_id>/messages`.

#### - Upload af filer i samtaler
Frontend sender filer som base64 i request-body, backend dekoder til bytes og gemmer dem som attachments på beskeder, så konteksten kan genbruges ved fortsat chat.

#### - Opbevaring af samtaler i Postgres
Samtaler og beskeder persistéres i Postgres (Conversation/Message/Attachment/Reference) og opdateres løbende, når der sendes nye bruger- og assistentbeskeder.

#### - Indlæsning af samtaler med nøvendige rettigheder
Samtaler kan kun indlæses via en kortlivet, signeret “load permit” (RS256) gennem `POST /api/conversations/load` (legacy `GET /api/conversations/<id>` er deaktiveret).

#### - Sikker tovejskommunikation med [ai-chat-portal](https://github.com/Randers-Kommune-Digitalisering/ai-chat-portal) (til samtalehistorik)
Portalen kan indlæse samtaler ved at udstede et permit, som app’en validerer, og frontend kan sende/rydde samtaler samt synkronisere state via portal messaging. Læs mere om [sikret indlæsning af samtaler her](https://github.com/Randers-Kommune-Digitalisering/ai-chat-portal/blob/development/README.md#sikret-indl%C3%A6sning-af-samtaler-portal--indlejret-chat-app).

#### - Generering af samtaletitler
Samtaler der lagres i Postgres-database bliver automatisk tildelt en beskrivende titel, genereret af separat AI-model.

#### - CPR-filtrering til at opfange følsomme oplysninger inden afsendelse
Backend matcher CPR-numre med regex og kan returnere fund via `POST /api/filter`, så klienten kan advare/handle før afsendelse.

#### - Anonymisering af følsomme oplysninger

Før beskeder sendes til Azure, bliver følsomt indhold redigeret ud (fx CPR) ved at erstatte fund med placeholders som `[REDACTED #1]`.

#### - Alternativ assistent toggle

Der kan udstilles to forskellige assistenter i samme chatvindue med en visuel toggle til at skifte mellem disse. Brugere kan med denne feature skifte mellem de to assistenter i løbet af en samtale.

## Miljøvariabler
Applikationen er afhængig af en række miljøvariabler. De nødvendige miljøvariabler afhænger af assistentens type, `ASSISTANT_TYPE`.

### Nødvendige miljøvariabler
Disse skal altid være sat (uanset assistent-type), da de bruges uden sikre defaults.

* **`ASSISTANT_TYPE`** (default: `Chat`)

	Vælger kørselstype: `Agent`/`Assistant` eller `Chat`.

* **`ASSISTANT_NAME`** (default: `AI Assistent`)

	Visningsnavn i UI.

* **`ASSISTANT_NAME_ID`** (default: `default-assistant`)

	ID som portalen bruger til at identificere assistenten.

* **`PREDEFINED_QUESTIONS`**

	Semikolon-separeret liste af forslagsspørgsmål (fx `Spg1;Spg2`).


* **`AZURE_OPENAI_KEY`**

	API-nøgle til Azure OpenAI.

* **`AZURE_OPENAI_ENDPOINT`**

	Base endpoint for Azure OpenAI-ressourcen.

* **`AZURE_OPENAI_DEPLOYMENT_NAME`**

	Deployment/model-navn der bruges til chat.

* **`AZURE_API_VERSION_OPENAI`** (default: `2024-12-01-preview`)

	API-version for OpenAI endpoints.


* **`FEEDBACK_MAIL_API_URL`**

	Endpoint til feedback-mail service.

* **`FEEDBACK_MAIL_API_RECIPIENT`**

	Modtageradresse for feedback.

* **`FEEDBACK_MAIL_API_SENDER`**

	Afsenderadresse for feedback.

### Chat-type miljøvariabler
Skal sættes når `ASSISTANT_TYPE` er `Chat`.

* **`SYSTEM_PROMPT`** (default: `Du er en hjælpsom AI-assistent.`)

	System prompt for chat.

* **`USE_GENERAL_KNOWLEDGE`** (default: `True`)

	Om assistenten må bruge generel viden ud over kilder/dokumenter.

* **`EMPHASIZE_RECENT_CONTENT`** (default: `True`)

	Om nyligt indhold vægtes højere i prompt-kontekst.

* **`TOP_P_VALUE`** (default: `0.8`)

	Sampling-parameter (top-p).

* **`TEMPERATURE_VALUE`** (default: `0.2`)

	Sampling-parameter (temperature).

### Agent-type miljøvariabler
Skal sættes når `ASSISTANT_TYPE` er `Agent`.

* **`ASSISTANT_ID`**

	Azure agent-id.

* **`AZURE_AIFOUNDRY_PROJECT_NAME`**

	Project-navn til Azure AI Foundry.

### Valgfrie miljøvariabler

* **`ASSISTANT_ALT_ID`**

	Sekundær assistant-id til assistent-toggle (sætter `SHOW_ASSISTANT_TOGGLE`), hvis `ASSISTANT_TYPE` er `agent`.

* **`ALT_TOGGLE_LABEL`** (default: `Brug alternativ assistent`).

	Label for alternativ assistent-toggle i UI, hvis `ASSISTANT_ALT_ID` er sat.

* **`ALT_ALERT_MSG`** (default: tom).

	Alert-tekst der kan vises ifm. alternativ assistent, hvis `ASSISTANT_ALT_ID` er sat.

* **`ALT_ALERT_TYPE`** (default: `info`).

	Alert-type for alternativ assistent (`info`, `warning`, `danger`), hvis `ALT_ALERT_MSG` er sat.


* **`ALLOW_FILE_UPLOAD`** (default: `False`)

	Slår fil-upload til/fra.


* **`AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION`** (alias: `AZURE_OPENAI_DEPLOYMENT_NAME`)

	Deployment/model-navn til automatisk titelgenerering.

* **`AZURE_AISEARCH_INDEX_NAME`**

	Index-navn i Azure AI Search (hvis retrieval anvendes), kan kun anvendes hvis `ASSISTANT_TYPE` er `chat`.

* **`AZURE_AISEARCH_ENDPOINT`**

	Endpoint for Azure AI Search, hvis `AZURE_AISEARCH_INDEX_NAME` er sat.

* **`AZURE_AISEARCH_SEMANTIC_CONFIG`** (default: `default-semantic-config`)

	Navn på semantic configuration i Azure AI Search, hvis `AZURE_AISEARCH_INDEX_NAME` er sat.

* **`AZURE_API_VERSION_FILES`** (default: `2024-10-21`)

	API-version for file endpoints, hvis `AZURE_AISEARCH_INDEX_NAME` er sat.

* **`TOP_N_DOCUMENTS`** (default: `10`)

	Antal dokumenter der hentes fra search/retrieval, hvis `AZURE_AISEARCH_INDEX_NAME` er sat.

* **`SEARCH_STRICTNESS`** (default: `3`)

	Stramhed for søgning/retrieval, hvis `AZURE_AISEARCH_INDEX_NAME` er sat.




* **`POSTGRES_USER`** (default: `postgres`)

	Postgres brugernavn.

* **`POSTGRES_PASSWORD`** (default: `mysecretpassword`)

	Postgres password.

* **`POSTGRES_HOST`** (default: `localhost`)

	Postgres host.

* **`POSTGRES_PORT`** (default: `5432`)

	Postgres port.

* **`POSTGRES_DB`** (default: `ai_chat_db`)

	Postgres databasenavn.


* **`CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM`** (default: tom)

	RS256 public key (PEM) til validering af portalens load-permits.

* **`CONVERSATION_LOAD_PERMIT_ISSUER`** (default: `gpt-dashboard-portal`)

	Forventet JWT issuer for load-permit.

* **`CONVERSATION_LOAD_PERMIT_AUDIENCE`** (default: `chat-app`)

	Forventet JWT audience for load-permit.

* **`CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS`** (default: tom)

	Komma-separeret liste af tilladte `kid` værdier fra JWT header.

* **`CSP_FRAME_ANCESTORS`** (default: tom)

	Hvis sat, begrænser hvem der må embedde app’en (CSP `frame-ancestors`).


* **`DEBUG`** (default: `False`)

	Aktiverer debug-funktionalitet i backend.

* **`PORT`** (default: `8080`)

	Port som backend skal lytte på.

* **`POD_NAME`** (default: `pod_name_not_set`)

	Instance-navn (bruges bl.a. til metrik-labels).


* **`METRICS_APP`** (default: `ai-chat-app`)

	Prometheus label: applikationsnavn.

* **`METRICS_DEPLOYMENT`** (alias: `DEPLOYMENT`, default: `unknown`)

	Prometheus label: deployment-miljø/navn.

* **`METRICS_INSTANCE`** (default: `POD_NAME`)

	Prometheus label: instans (typisk pod/container).

## Metrics
Brugsstatistik trackes og udstilles med følgende Prometheus-metrikker på `/metrics`:

* `chat_messages_total{app, deployment, instance, mode}`
	* Tæller antal bruger-beskeder modtaget af backend.
	* `mode` er `chat` eller `agent`.

* `chat_feedback_total{app, deployment, instance, feedback_type}`
	* Tæller feedback events.
	* `feedback_type` er `like` (thumbs up) eller `custom` (tekstfeedback sendt).

Metrikkerne er afhængige af følgende miljøvariabler:

* `METRICS_APP` (default: `ai-chat-app`)
* `METRICS_DEPLOYMENT` (alias: `DEPLOYMENT`, default: `unknown`)
* `METRICS_INSTANCE` (alias: `POD_NAME`)

## Udvikling

* Kørsel af Frontenden (Vue): ```cd vue && npm install && npm run dev```
* Kørsel af Bakcenden (Python): ```python flask/src/main.py```
* Kørsel af frontend + backend i docker: ```docker-compose up``` i top dir (backend på port 8080, frontend på port 3000)
* Bygge docker image: ```docker build -t ai-chat-app .```
* Kør container ud fra det image man byggede: ```docker run -p 8080:8080 ai-chat-app```
* Lint: ```flake8 python/src tests --count --ignore=E501,W503 --show-source --statistics```
* Unit tests: ``` pytest ```

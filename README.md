# ai-chat-app
Applikationen udstiller et webbasseret chat-interface til afvikling af samtaler med AI-assistenter via Azure OpenAI API-endpoints. Samtaler opbevares i Postgres database. 

Løsningen kan fungere som chatvindue i [ai-chat-portal](https://github.com/Randers-Kommune-Digitalisering/ai-chat-portal) - en chatportal til udstilling af forskellige assistenter med brugerstyret samtalehistorik. 

## Features

#### :robot: Chat med AI-assistenter fra Azure (ChatCompletions eller Agent)
Backend vælger mellem den understøttede legacy ChatCompletions-klient og den nye AI Foundry Agent-klient via `ASSISTANT_TYPE`. Chat-kilder vises med navngivne inline-referencer på samme måde som Agent-kilder.

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
Konfiguration indlæses fra miljøet og fra en lokal `.env`-fil. Gem ikke nøgler eller passwords i Git; injicér dem via den godkendte secret store i det relevante miljø.

`ASSISTANT_TYPE` vælger klienten og bør sættes eksplicit til enten `Chat` eller `Agent`. Værdien har default `Chat`. Andre værdier behandles også som Chat, så brug det dokumenterede navn for at undgå fejlkonfiguration.

### Nødvendige for begge typer

Følgende værdier læses uden default og skal altid være sat. Deployment-navnet bruges også som fallback til automatisk titelgenerering.

| Navn | Beskrivelse |
|---|---|
| `AZURE_OPENAI_KEY` | API-nøgle til Azure OpenAI. |
| `AZURE_OPENAI_ENDPOINT` | Base-endpoint for Azure OpenAI-ressourcen. |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Deployment/model til Chat og fallback-model til titelgenerering. |

### Chat

Sæt `ASSISTANT_TYPE=Chat` for den understøttede legacy ChatCompletions-klient. Der kræves ingen yderligere værdier ud over de tre fælles værdier.

Minimal konfiguration:

```dotenv
ASSISTANT_TYPE=Chat
AZURE_OPENAI_KEY=<secret>
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=<deployment>
```

Valgfrie Chat-indstillinger:

| Navn | Default | Beskrivelse |
|---|---:|---|
| `SYSTEM_PROMPT` | `Du er en hjælpsom AI-assistent.` | Systemprompt for Chat-klienten. |
| `USE_GENERAL_KNOWLEDGE` | `True` | Om svar må bruge generel viden ud over søgeresultater. |
| `EMPHASIZE_RECENT_CONTENT` | `True` | Tilføjer dags dato og instruktion om at prioritere ny information. |
| `TOP_P_VALUE` | `0.8` | Sampling-parameteren `top_p`. |
| `TEMPERATURE_VALUE` | `0.2` | Sampling-parameteren `temperature`. |
| `MAX_TOKEN_LIMIT` | `1000000` | Maksimalt samlet antal tokens i systemprompt og samtalehistorik. |
| `DEFAULT_TOKEN_ENCODING` | `cl100k_base` | Tokenizer-fallback, hvis deployment-navnet ikke genkendes af `tiktoken`. |

Azure AI Search er valgfrit for Chat. Retrieval aktiveres kun, når både endpoint og index er sat:

| Navn | Default | Krav/beskrivelse |
|---|---:|---|
| `AZURE_AISEARCH_ENDPOINT` | — | Påkrævet, når Azure AI Search anvendes. |
| `AZURE_AISEARCH_INDEX_NAME` | — | Påkrævet, når Azure AI Search anvendes. |
| `AZURE_AISEARCH_SEMANTIC_CONFIG` | `default-semantic-config` | Semantic configuration på indexet. |
| `TOP_N_DOCUMENTS` | `10` | Maksimalt antal dokumenter fra retrieval. |
| `SEARCH_STRICTNESS` | `3` | Stramhed for retrieval. |

### Agent

Sæt `ASSISTANT_TYPE=Agent` for AI Foundry Conversations/Responses-klienten. Agent-klienten bruger `DefaultAzureCredential`; den kørende identitet skal derfor have mindst mulige nødvendige rettigheder til det valgte Foundry-projekt.

Ud over de fælles værdier kræves:

| Navn | Beskrivelse |
|---|---|
| `AGENT_ID` | Navnet/id'et på AI Foundry-agenten. `ASSISTANT_ID` understøttes som legacy-alias. |
| `AZURE_AIFOUNDRY_PROJECT_ENDPOINT` | Fuldt project endpoint. `FOUNDRY_PROJECT_ENDPOINT` understøttes som alias. Hvis ingen af dem sættes, er `AZURE_AIFOUNDRY_PROJECT_NAME` påkrævet. |

Minimal konfiguration med fuldt endpoint:

```dotenv
ASSISTANT_TYPE=Agent
AZURE_OPENAI_KEY=<secret>
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=<deployment>
AGENT_ID=<agent-name>
AZURE_AIFOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
```

Alternativt kan `AZURE_AIFOUNDRY_PROJECT_NAME=<project>` bruges i stedet for et fuldt project endpoint. I så fald bygger klienten endpointet efter løsningens eksisterende Randers-specifikke URL-format.

Valgfrie Agent-indstillinger:

| Navn | Default | Beskrivelse |
|---|---:|---|
| `FOUNDRY_AGENT_VERSION` | — | Version for den primære agent reference. |
| `AGENT_ALT_ID` | — | Alternativ agent til UI-toggle. `ASSISTANT_ALT_ID` understøttes som legacy-alias. |
| `FOUNDRY_AGENT_ALT_VERSION` | — | Version for den alternative agent reference. |
| `AGENT_FILE_METADATA_ONLY` | `True` | Gem kun filnavn, MIME-type og størrelse i den lokale database for Agent-uploads. Sæt til `False` for også at gemme base64-kodet filindhold. Påvirker ikke upload til Foundry. |
| `ALT_TOGGLE_LABEL` | `Brug alternativ assistent` | Label for agent-toggle. |
| `ALT_ALERT_MSG` | — | Alert-tekst for den alternative agent. |
| `MAX_MESSAGE_LENGTH` | `256000` | Maksimal længde af brugerens tekst i tegn. |
| `AGENT_FILE_SIZE_LIMIT` | `100MB` | Maksimal størrelse pr. uploadet Agent-fil. Understøtter `B`, `KB`, `MB` og `GB`. |
| `ALT_ALERT_TYPE` | `info` | Alert-type: `info`, `warning` eller `danger`. |
| `AZURE_AISEARCH_ENDPOINT` | — | Påkrævet hvis agenten anvender Azure AI Search tool. |
| `AZURE_AISEARCH_API_KEY` | — | Påkrævet hvis agenten anvender Azure AI Search tool. |

### Fælles valgfrie indstillinger

| Navn | Default | Beskrivelse |
|---|---:|---|
| `ASSISTANT_NAME` | `AI Assistent` | Visningsnavn i UI. |
| `ASSISTANT_NAME_ID` | `default-assistant` | ID som portalen bruger til at identificere assistenten. |
| `ASSISTANT_DESCRIPTION` | — | Beskrivelse, der vises i UI. |
| `PREDEFINED_QUESTIONS` | — | Semikolonseparerede forslagsspørgsmål, eksempelvis `Spørgsmål 1;Spørgsmål 2`. |
| `ALLOW_FILE_UPLOAD` | `False` | Reserveret indstilling; er aktuelt ikke aktiv. |
| `MAX_TOKEN_LIMIT_MESSAGE` | `98304` | Maksimalt antal tokens for enkelt besked (inklusiv filer for Chat, eksklusiv for Agent) |
| `AZURE_API_VERSION_OPENAI` | `2024-12-01-preview` | API-version til Azure OpenAI. |
| `AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION` | `AZURE_OPENAI_DEPLOYMENT_NAME` | Separat deployment til automatisk titelgenerering. |
| `TITLE_GENERATION_MAX_CONCURRENCY` | `100` | Maksimalt antal samtidige titelgenereringer pr. proces; minimum er `10`. |
| `TITLE_GENERATION_REQUEST_TIMEOUT_S` | `8` | Timeout for kaldet til titelmodellen. |
| `TITLE_GENERATION_JOIN_TIMEOUT_S` | `9` | Maksimal ventetid på titeltråden i request-flowet. |
| `DEBUG` | `False` | Aktiverer backend-debug. |
| `PORT` | `8080` | Backendens lytteport. |
| `CSP_FRAME_ANCESTORS` | — | Begrænser hvilke origins der må embedde appen via CSP `frame-ancestors`. |

### Valgfrie integrationer

Postgres er deaktiveret, medmindre alle forbindelsesværdier er sat. Brug en separat databasebruger med minimale rettigheder, TLS og kryptering ved lagring. Testmiljøer må ikke anvende produktionsdata.

| Navn | Default | Krav/beskrivelse |
|---|---:|---|
| `POSTGRES_USER` | — | Påkrævet for databasepersistens. |
| `POSTGRES_PASSWORD` | — | Påkrævet for databasepersistens; skal leveres som secret. |
| `POSTGRES_HOST` | — | Påkrævet for databasepersistens. |
| `POSTGRES_PORT` | `5432` | PostgreSQL-port. |
| `POSTGRES_DB` | — | Påkrævet for databasepersistens. |

Feedbackmail kræver SMTP-server og mindst én modtager. Afsenderfelter afhænger af SMTP-serverens krav.

| Navn | Default | Krav/beskrivelse |
|---|---:|---|
| `FEEDBACK_SMTP_SERVER` | — | Påkrævet for feedbackmail. |
| `FEEDBACK_MAIL_RECIPIENT` | — | Påkrævet for feedbackmail; flere adresser separeres med komma eller semikolon. |
| `FEEDBACK_SMTP_PORT` | `25` | SMTP-port. |
| `FEEDBACK_SMTP_SENDER_EMAIL` | — | Afsenderadresse og eventuelt SMTP-login. Manglende domæne suppleres med `@randers.dk`. |
| `FEEDBACK_SMTP_SENDER_PASSWORD` | — | Valgfrit SMTP-password; skal leveres som secret. |
| `FEEDBACK_SMTP_SENDER_NAME` | — | Valgfrit visningsnavn for afsenderen. |

Portalens samtaleindlæsning kræver en offentlig RS256-nøgle. Uden nøglen kan load-permits ikke valideres.

| Navn | Default | Krav/beskrivelse |
|---|---:|---|
| `CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM` | — | Påkrævet for permit-baseret samtaleindlæsning. |
| `CONVERSATION_LOAD_PERMIT_ISSUER` | `gpt-dashboard-portal` | Forventet JWT issuer. |
| `CONVERSATION_LOAD_PERMIT_AUDIENCE` | `chat-app` | Forventet JWT audience. |
| `CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS` | — | Valgfri allow-list af JWT `kid`-værdier, separeret med komma eller semikolon. |

### Metrics og runtime

| Navn | Default | Beskrivelse |
|---|---:|---|
| `POD_NAME` | `pod_name_not_set` | Instance-navn og fallback til metrics-label. |
| `METRICS_APP` | `ai-chat-app` | Prometheus-label for applikationen. |
| `METRICS_DEPLOYMENT` | `unknown` | Prometheus-label for miljø/deployment; `DEPLOYMENT` er fallback. |
| `METRICS_INSTANCE` | `POD_NAME` | Prometheus-label for instansen. |

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

Yderligere metrikker der primært bruges til debugging:

* `title_generation_saturation_total{app, deployment, instance, mode}`
	* Tæller antal gange titelgenerering blev sprunget over pga. concurrency-grænse.
	* `mode` er `chat` eller `agent`.

* `title_generation_timeout_total{app, deployment, instance, mode}`
	* Tæller antal gange ventetiden på titelgenerering overskred join-timeout, så fallback-titel blev brugt.
	* `mode` er `chat` eller `agent`.

* `title_generation_inflight{app, deployment, instance, mode}`
	* Gauge for antal titelgenereringer, der er i gang lige nu.
	* `mode` er `chat` eller `agent`.

De tilhørende miljøvariabler er beskrevet under **Metrics og runtime** i miljøvariabelafsnittet.

## Udvikling

* Kørsel af Frontenden (Vue): ```cd vue && npm install && npm run dev```
* Kørsel af Bakcenden (Python): ```python flask/src/main.py```
* Kørsel af frontend + backend i docker: ```docker-compose up``` i top dir (backend på port 8080, frontend på port 3000)
* Bygge docker image: ```docker build -t ai-chat-app .```
* Kør container ud fra det image man byggede: ```docker run -p 8080:8080 ai-chat-app```
* Lint: ```flake8 python/src tests --count --ignore=E501,W503 --show-source --statistics```
* Unit tests: ``` pytest ```

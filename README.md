# ai-chat-app
Dokumentation kommer snart.

## Kørsel af frontend + backend i docker
* Kør ```docker-compose up``` i top dir
* Backend på port 8080, frontend på port 3000

## Kørsel af Frontenden(Vue)
* CD hen til vue folder: ``` cd vue ```
* Installerer afhængigheder: ``` npm install ```
* Compile, hot reload og start frontenden: ``` npm run dev ```

## Kørsel af Bakcenden(Python)
* Start applikationen: ``` python flask/src/main.py ```

## Prometheus metrics
Backend eksponerer Prometheus metrics på `/metrics`.

### Metrics
* `chat_messages_total{app, deployment, instance, mode}`
	* Tæller antal bruger-beskeder modtaget af backend.
	* `mode` er `chat` eller `agent`.
* `chat_feedback_total{app, deployment, instance, feedback_type}`
	* Tæller feedback events.
	* `feedback_type` er `like` (thumbs up) eller `custom` (tekstfeedback sendt).

### Label env vars
Disse labels gør det muligt at skelne mellem deployments (og pods/instances):
* `METRICS_APP` (default: `ai-chat-app`)
* `METRICS_DEPLOYMENT` (default: `DEPLOYMENT` eller `unknown`)
* `METRICS_INSTANCE` (default: `POD_NAME`)

## Udviklings commands:
* Bygge docker image: ```docker build -t vue-python-template .```
* Kør container ud fra det image man byggede: ```docker run -p 8080:8080 vue-python-template```
* Lint: ```flake8 python/src tests --count --select=E9,F63,F7,F82 --show-source --statistics```
* Unit tests: ``` pytest ```



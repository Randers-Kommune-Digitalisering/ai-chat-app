import os
from dotenv import load_dotenv


# loads .env file, will not overide already set enviroment variables (will do nothing when testing, building and deploying)
load_dotenv()


DEBUG = os.getenv('DEBUG', 'False') in ['True', 'true']
PORT = os.getenv('PORT', '8080')
POD_NAME = os.getenv('POD_NAME', 'pod_name_not_set')

# Prometheus metric labels (used to distinguish deployments/instances)
METRICS_APP = os.getenv('METRICS_APP', 'ai-chat-app').strip()
METRICS_DEPLOYMENT = os.getenv('METRICS_DEPLOYMENT', os.getenv('DEPLOYMENT', 'unknown')).strip() or 'unknown'
METRICS_INSTANCE = os.getenv('METRICS_INSTANCE', POD_NAME).strip() or POD_NAME

AZURE_OPENAI_KEY = os.environ.get('AZURE_OPENAI_KEY').strip()
AZURE_OPENAI_ENDPOINT = os.environ.get('AZURE_OPENAI_ENDPOINT').strip()
AZURE_OPENAI_DEPLOYMENT_NAME = os.environ.get('AZURE_OPENAI_DEPLOYMENT_NAME').strip()
AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION = os.environ.get('AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION', '').strip()
if not AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION:
    AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION = AZURE_OPENAI_DEPLOYMENT_NAME
AZURE_AISEARCH_ENDPOINT = os.environ.get('AZURE_AISEARCH_ENDPOINT', '').strip()
AZURE_AISEARCH_INDEX_NAME = os.environ.get('AZURE_AISEARCH_INDEX_NAME', '').strip()
AZURE_AISEARCH_SEMANTIC_CONFIG = os.environ.get('AZURE_AISEARCH_SEMANTIC_CONFIG', 'default-semantic-config').strip()
AZURE_AIFOUNDRY_PROJECT_NAME = os.environ.get('AZURE_AIFOUNDRY_PROJECT_NAME', '').strip()  # Used for Agents only
AZURE_API_VERSION_OPENAI = os.environ.get('AZURE_API_VERSION_OPENAI', '2024-12-01-preview').strip()
AZURE_API_VERSION_FILES = os.environ.get('AZURE_API_VERSION_FILES', '2024-10-21').strip()

ASSISTANT_NAME = os.environ.get('ASSISTANT_NAME', 'AI Assistent').strip()  # Display name
ASSISTANT_NAME_ID = os.environ.get('ASSISTANT_NAME_ID', 'default-assistant').strip()  # ID used in portal (i.e. randers-gpt)
ASSISTANT_TYPE = os.environ.get('ASSISTANT_TYPE', 'Chat').strip()  # Enum: Agent or Chat
ASSISTANT_ID = os.environ.get('ASSISTANT_ID')  # If type is Agent, this must be set
ASSISTANT_ALT_ID = os.environ.get('ASSISTANT_ALT_ID', None)  # Second assistant ID for assistant toggle
if str(ASSISTANT_TYPE).lower() in ['agent', 'assistant']:
    ASSISTANT_ID = ASSISTANT_ID.strip()
    if ASSISTANT_ALT_ID is not None:
        ASSISTANT_ALT_ID = ASSISTANT_ALT_ID.strip()
SHOW_ASSISTANT_TOGGLE = bool(ASSISTANT_ALT_ID)

SYSTEM_PROMPT = os.environ.get('SYSTEM_PROMPT', "Du er en hjælpsom AI-assistent.").strip()
PREDEFINED_QUESTIONS = [q for q in os.getenv("PREDEFINED_QUESTIONS", "").split(";") if q.strip()]
ASSISTANT_DESCRIPTION = os.environ.get('ASSISTANT_DESCRIPTION', '').strip()

ALT_TOGGLE_LABEL = os.environ.get('ALT_TOGGLE_LABEL', "Brug alternativ assistent").strip()
ALT_ALERT_MSG = os.environ.get('ALT_ALERT_MSG', '').strip()
ALT_ALERT_TYPE = os.environ.get('ALT_ALERT_TYPE', 'info').strip()  # info, warning, danger

EMPHASIZE_RECENT_CONTENT = os.environ.get('EMPHASIZE_RECENT_CONTENT', 'True') in ['True', 'true']
USE_GENERAL_KNOWLEDGE = os.environ.get('USE_GENERAL_KNOWLEDGE', 'True') in ['True', 'true']
try:
    TOP_P_VALUE = float(os.environ.get('TOP_P_VALUE', 0.8))
except ValueError:
    TOP_P_VALUE = 0.8
try:
    TEMPERATURE_VALUE = float(os.environ.get('TEMPERATURE_VALUE', 0.2))
except ValueError:
    TEMPERATURE_VALUE = 0.2
try:
    TOP_N_DOCUMENTS = int(os.environ.get('TOP_N_DOCUMENTS', 10))
except ValueError:
    TOP_N_DOCUMENTS = 10
try:
    SEARCH_STRICTNESS = int(os.environ.get('SEARCH_STRICTNESS', 3))
except ValueError:
    SEARCH_STRICTNESS = 3

FEEDBACK_MAIL_API_URL = os.environ.get('FEEDBACK_MAIL_API_URL').strip()
FEEDBACK_MAIL_API_RECIPIENT = os.environ.get('FEEDBACK_MAIL_API_RECIPIENT').strip()
FEEDBACK_MAIL_API_SENDER = os.environ.get('FEEDBACK_MAIL_API_SENDER').strip()

ALLOW_FILE_UPLOAD = os.environ.get('ALLOW_FILE_UPLOAD', 'False') in ['True', 'true']

# Max length of the user message when using Agent-mode (currently including any appended document content)
try:
    MAX_MESSAGE_LENGTH = int(os.environ.get('MAX_MESSAGE_LENGTH', 256000))
except ValueError:
    MAX_MESSAGE_LENGTH = 256000

# Max token limit for chat history when using Chat-mode (including any appended document content)
try:
    MAX_TOKEN_LIMIT_HISTORY = int(os.environ.get('MAX_TOKEN_LIMIT', 1000000))
except ValueError:
    MAX_TOKEN_LIMIT_HISTORY = 1000000

# Max token limit for each user message when using Chat-mode (currently including any appended document content)
try:
    MAX_TOKEN_LIMIT_MESSAGE = int(os.environ.get('MAX_TOKEN_LIMIT_MESSAGE', 129024))
except ValueError:
    MAX_TOKEN_LIMIT_MESSAGE = 129024

DEFAULT_TOKEN_ENCODING = os.environ.get('DEFAULT_TOKEN_ENCODING', 'cl100k_base').strip()  # Used for token counting, e.g. with tiktoken

# requests/urllib3 connection pooling (affects Azure SDK clients using RequestsTransport, and any custom requests.Session)
try:
    REQUESTS_POOL_CONNECTIONS = int(os.environ.get('REQUESTS_POOL_CONNECTIONS', 10))
except ValueError:
    REQUESTS_POOL_CONNECTIONS = 100
try:
    REQUESTS_POOL_MAXSIZE = int(os.environ.get('REQUESTS_POOL_MAXSIZE', 100))
except ValueError:
    REQUESTS_POOL_MAXSIZE = 100
# If True, requests will block when the pool is exhausted instead of opening/discarding extra connections.
REQUESTS_POOL_BLOCK = os.environ.get('REQUESTS_POOL_BLOCK', 'False') in ['True', 'true']

POSTGRES_USER = os.environ.get('POSTGRES_USER', '').strip()
POSTGRES_PASS = os.environ.get('POSTGRES_PASSWORD', '').strip()
POSTGRES_HOST = os.environ.get('POSTGRES_HOST', '').strip()
POSTGRES_PORT = os.environ.get('POSTGRES_PORT', '5432').strip()
POSTGRES_DB = os.environ.get('POSTGRES_DB', '').strip()
USE_DB = all([POSTGRES_DB, POSTGRES_USER, POSTGRES_PASS, POSTGRES_HOST, POSTGRES_PORT])

# Permit-based conversation loading (portal -> iframe chat-app)
# The portal issues a short-lived RS256-signed JWT/JWS permit.
CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM = os.environ.get('CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM', '').strip()
CONVERSATION_LOAD_PERMIT_ISSUER = os.environ.get('CONVERSATION_LOAD_PERMIT_ISSUER', 'gpt-dashboard-portal').strip()
CONVERSATION_LOAD_PERMIT_AUDIENCE = os.environ.get('CONVERSATION_LOAD_PERMIT_AUDIENCE', 'chat-app').strip()

# Optional: comma-separated list of allowed JWT header kid values.
CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS = [
    s.strip() for s in os.environ.get('CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS', '').split(',') if s.strip()
]

# Optional: restrict who can embed this app.
# If the value does not include the directive name, it will be prefixed with `frame-ancestors `.
# Example: "'self' https://chat.data.randers.dk https://ai.data.randers.dk"
CSP_FRAME_ANCESTORS = os.environ.get('CSP_FRAME_ANCESTORS', '').strip()

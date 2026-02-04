// Lightweight portal <-> iframe messaging helpers
let hostname = ""
if (typeof window !== 'undefined') {
	hostname = window.location.hostname
}
function deriveDomainFromHostname(currentHostname) {
	const host = (currentHostname ?? '').trim().toLowerCase()
	if (!host) return ''

	// If the hostname has multiple subdomains (e.g. chat.data.randers.dk),
	// drop the left-most label to get the base domain (data.randers.dk).
	const parts = host.split('.').filter(Boolean)
	if (parts.length >= 3) return parts.slice(1).join('.')
	return host
}
const domain = deriveDomainFromHostname(hostname)
const ALLOWED_ORIGINS = [
	'http://localhost:3000',
	`https://chat.${domain}`,
	`https://ai.${domain}`
];

export function isPortalDebugEnabled() {
	try {
		return (
			import.meta.env?.DEV ||
			import.meta.env?.VITE_PORTAL_DEBUG === '1' ||
			window?.localStorage?.getItem('portalDebug') === '1'
		);
	} catch {
		return false;
	}
}

export function portalDebugLog(...args) {
	if (!isPortalDebugEnabled()) return;
	// Prefix helps distinguish iframe logs from parent logs
	console.log('[ai-chat iframe]', ...args);
}

function getAllowedOrigins() {
	const raw = ALLOWED_ORIGINS; // import.meta.env.VITE_PORTAL_ORIGINS;
	if (!raw) return [];
	return String(raw)
		.split(',')
		.map(s => s.trim())
		.filter(Boolean);
}

export function isAllowedPortalOrigin(origin) {
	const allowed = getAllowedOrigins();
	portalDebugLog('Checking allowed origins:', allowed, 'against', origin);
	if (allowed.length === 0) {
		// Secure-by-default: if no allowlist is configured, only accept same-origin.
		portalDebugLog('No allowed origins configured, enforcing same-origin policy. Checking origin ', window.location.origin, ' against ', origin, ' with result:', origin === window.location.origin);
		return origin === window.location.origin;
	}
	return allowed.includes(origin);
}

export function normalizePortalMessage(data) {
	if (!data || typeof data !== 'object') return null;
	if (typeof data.type !== 'string') return null;
	// portalDebugLog('Normalized message:', data);
	return data;
}

export function notifyParentReady() {
	// Optional handshake: lets the parent know the iframe is ready to receive messages.
	if (!window.parent || window.parent === window) return;

	const allowed = getAllowedOrigins();
	const targets = allowed.length > 0 ? allowed : [window.location.origin];
	portalDebugLog('Sending IFRAME_READY to:', targets);
	for (const targetOrigin of targets) {
		window.parent.postMessage({ type: 'IFRAME_READY', version: 1 }, targetOrigin);
	}
}

export function notifyParentLoaded() {
	// Lets the parent know the requested conversation has loaded.
	if (!window.parent || window.parent === window) return;

	const allowed = getAllowedOrigins();
	const targets = allowed.length > 0 ? allowed : [window.location.origin];
	portalDebugLog('Sending IFRAME_CONTENT_LOADED to:', targets);
	for (const targetOrigin of targets) {
		window.parent.postMessage({ type: 'IFRAME_CONTENT_LOADED', version: 1 }, targetOrigin);
	}
}

export function notifyParentNewConversation(conversation) {
	// Lets the parent know a new conversation has been created.
	if (!window.parent || window.parent === window) return;

	const allowed = getAllowedOrigins();
	const targets = allowed.length > 0 ? allowed : [window.location.origin];
	portalDebugLog('Sending NEW_CONVERSATION to:', targets, 'with conversation:', conversation);
	for (const targetOrigin of targets) {
		window.parent.postMessage({ type: 'NEW_CONVERSATION', version: 1, conversation }, targetOrigin);
	}
}

export function notifyParentChatCleared(payload = {}) {
	// Lets the parent know the chat has been cleared/reset.
	if (!window.parent || window.parent === window) return;

	const allowed = getAllowedOrigins();
	const targets = allowed.length > 0 ? allowed : [window.location.origin];
	portalDebugLog('Sending CHAT_CLEARED to:', targets, 'with payload:', payload);
	for (const targetOrigin of targets) {
		window.parent.postMessage({ type: 'CHAT_CLEARED', version: 1, ...payload }, targetOrigin);
	}
}

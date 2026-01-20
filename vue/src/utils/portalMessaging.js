// Lightweight portal <-> iframe messaging helpers
const ALLOWED_ORIGINS = ['http://localhost:3000'];


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
	portalDebugLog('Normalized message:', data);
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

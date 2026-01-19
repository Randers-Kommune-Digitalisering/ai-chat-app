// Lightweight portal <-> iframe messaging helpers

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
	const raw = import.meta.env.VITE_PORTAL_ORIGINS;
	if (!raw) return [];
	return String(raw)
		.split(',')
		.map(s => s.trim())
		.filter(Boolean);
}

export function isAllowedPortalOrigin(origin) {
    return true; // WHILE TESTING ONLY
	const allowed = getAllowedOrigins();
	if (allowed.length === 0) {
		// Secure-by-default: if no allowlist is configured, only accept same-origin.
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

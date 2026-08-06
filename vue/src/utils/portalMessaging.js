// Lightweight portal <-> iframe messaging helpers
// Policy: the only allowed origin is the iframe's *direct parent* origin.
// We lock the parent origin using browser hints (referrer/ancestorOrigins) or the first
// validated message event that comes from `window.parent`.

let rememberedParentOrigin = '';
let rememberedAllowedOrigins = null;

function normalizeOrigin(origin) {
	return String(origin ?? '')
		.trim()
		.replace(/\/$/, '')
		.toLowerCase();
}

function getAllowedPortalOrigins() {
	if (rememberedAllowedOrigins !== null) return rememberedAllowedOrigins;
	try {
		const raw = (import.meta.env?.VITE_PORTAL_ORIGINS ?? '').trim();
		if (!raw) {
			rememberedAllowedOrigins = [];
			return rememberedAllowedOrigins;
		}
		rememberedAllowedOrigins = raw
			.split(',')
			.map(s => normalizeOrigin(s))
			.filter(Boolean);
		return rememberedAllowedOrigins;
	} catch {
		rememberedAllowedOrigins = [];
		return rememberedAllowedOrigins;
	}
}

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
	console.debug('[ai-chat app]', ...args);
}

function tryDeriveOriginFromReferrer() {
	try {
		const ref = window?.document?.referrer;
		if (!ref) return '';
		const origin = new URL(ref).origin;
		return origin;
	} catch {
		return '';
	}
}

function tryDeriveOriginFromAncestorOrigins() {
	try {
		const ancestor = window?.location?.ancestorOrigins?.[0];
		if (typeof ancestor === 'string' && ancestor) return ancestor;
		return '';
	} catch {
		return '';
	}
}

function resolveParentOriginFromHints() {
	if (rememberedParentOrigin) return rememberedParentOrigin;

	const candidates = [tryDeriveOriginFromReferrer(), tryDeriveOriginFromAncestorOrigins()]
		.map(s => normalizeOrigin(s))
		.filter(Boolean);

	const origin = candidates[0] ?? '';
	if (!origin) return '';

	const allowed = getAllowedPortalOrigins();
	if (allowed.length > 0 && !allowed.includes(origin)) {
		// If an allowlist is configured, refuse to lock to an untrusted hint.
		return '';
	}

	rememberedParentOrigin = origin;
	portalDebugLog('Resolved parent origin from browser hints:', rememberedParentOrigin);
	return rememberedParentOrigin;
}

export function getPortalParentOrigin() {
	return rememberedParentOrigin || resolveParentOriginFromHints() || '';
}

export function isAllowedPortalMessageEvent(event) {
	try {
		if (!event) return false;
		if (!window?.parent || window.parent === window) return false;
		// Only accept messages from the *direct* parent window.
		if (event.source !== window.parent) return false;

		const origin = normalizeOrigin(event.origin);
		if (!origin) return false;

		const allowed = getAllowedPortalOrigins();
		if (allowed.length > 0 && !allowed.includes(origin)) return false;

		const locked = getPortalParentOrigin();
		if (!locked) {
			rememberedParentOrigin = origin;
			portalDebugLog('Locked parent origin from first parent message:', rememberedParentOrigin);
			return true;
		}

		return origin === normalizeOrigin(locked);
	} catch {
		return false;
	}
}

function postToParent(payload) {
	if (!window.parent || window.parent === window) return;

	const targetOrigin = getPortalParentOrigin();
	if (!targetOrigin) {
		portalDebugLog('No parent origin known yet; skipping postMessage:', payload?.type);
		return;
	}

	try {
		window.parent.postMessage(payload, targetOrigin);
	} catch (err) {
		portalDebugLog('postMessage failed for targetOrigin:', targetOrigin, err);
	}
}

export function normalizePortalMessage(data) {
	if (!data || typeof data !== 'object') return null;
	if (typeof data.type !== 'string') return null;
	// portalDebugLog('Normalized message:', data);
	return data;
}

export function notifyParentReady() {
	// Optional handshake: lets the parent know the iframe is ready to receive messages.
	postToParent({ type: 'IFRAME_READY', version: 1 });
}

export function notifyParentLoaded() {
	// Lets the parent know the requested conversation has loaded.
	postToParent({ type: 'IFRAME_CONTENT_LOADED', version: 1 });
}

export function notifyParentNewConversation(conversation) {
	// Lets the parent know a new conversation has been created.
	postToParent({ type: 'NEW_CONVERSATION', version: 1, conversation });
}

export function notifyParentChatCleared(payload = {}) {
	// Lets the parent know the chat has been cleared/reset.
	postToParent({ type: 'CHAT_CLEARED', version: 1, ...payload });
}

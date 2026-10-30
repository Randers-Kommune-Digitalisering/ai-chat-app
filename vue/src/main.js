import { createApp } from 'vue'
import './style.css'
import App from './App.vue'

// Debug: capture postMessage events even before Vue mounts.
// Enable with localStorage.setItem('portalDebug','1') (in the iframe) or VITE_PORTAL_DEBUG=1.
try {
	const debugEnabled =
		import.meta.env?.DEV ||
		import.meta.env?.VITE_PORTAL_DEBUG === '1' ||
		window?.localStorage?.getItem('portalDebug') === '1';

	if (debugEnabled) {
		console.debug('[ai-chat iframe] DEBUG: Bootstrap', {
			origin: window.location.origin,
			href: window.location.href
		});
		window.addEventListener('message', (e) => {
			// Ignore cross-extension window chatter (e.g. Selenium IDE) and only
			// log likely portal traffic from the direct parent frame.
			if (window.parent && window.parent !== window && e.source !== window.parent) return;
			if (!e.data || typeof e.data !== 'object') return;
			if (e.data.type === 'SELENIUM_IDE_CS_MSG') return;

			console.debug('[ai-chat main] DEBUG: Raw message received', {
				origin: e.origin,
				data: e.data
			});
		});
	}
} catch {
	// ignore debug bootstrap errors
}

// createApp(App).mount('#app')

const DEFAULT_CONFIG = {
	conversationLoadCutoffDate: '2026-09-15T00:00:00'
};

async function fetchConfig() {
	try {
		const res = await fetch('/api/config');
		if (!res.ok) {
			console.error('[ai-chat main] Failed to fetch /api/config', { status: res.status });
			return { ...DEFAULT_CONFIG };
		}
		const config = await res.json();
		return {
			...DEFAULT_CONFIG,
			...(config || {})
		};
	} catch (error) {
		console.error('[ai-chat main] Error fetching /api/config', error);
		return { ...DEFAULT_CONFIG };
	}
}

fetchConfig().then(config => {
	const app = createApp(App);
	app.config.globalProperties.$config = config;
    document.title = config.assistantName || "AI Chat";
	app.mount('#app');
});

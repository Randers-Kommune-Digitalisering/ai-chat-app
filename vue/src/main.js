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
		console.log('[ai-chat iframe] Bootstrap', {
			origin: window.location.origin,
			href: window.location.href
		});
		window.addEventListener('message', (e) => {
			console.log('[ai-chat iframe] Raw message received', {
				origin: e.origin,
				data: e.data
			});
		});
	}
} catch {
	// ignore debug bootstrap errors
}

// createApp(App).mount('#app')

async function fetchConfig() {
	const res = await fetch('/api/config');
	if (!res.ok) return {};
	return await res.json();
}

fetchConfig().then(config => {
	const app = createApp(App);
	app.config.globalProperties.$config = config;
    document.title = config.assistantName || "AI Chat";
	app.mount('#app');
});

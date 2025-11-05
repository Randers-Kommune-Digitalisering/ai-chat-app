import { createApp } from 'vue'
import './style.css'
import App from './App.vue'

// createApp(App).mount('#app')

async function fetchConfig() {
	const res = await fetch('/api/config');
	if (!res.ok) return {};
	return await res.json();
}

fetchConfig().then(config => {
	const app = createApp(App);
	app.config.globalProperties.$config = config;
	app.mount('#app');
});

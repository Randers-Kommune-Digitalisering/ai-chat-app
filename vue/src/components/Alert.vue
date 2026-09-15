<script setup>
    import { computed } from 'vue'
    import { marked } from 'marked'

    const renderer = new marked.Renderer();
    renderer.link = function(obj) {
        const href = obj.href
        const title = obj.title
        const text = obj.text
        // Add target and rel attributes
        const titleAttr = title ? ` title="${title}"` : ''
        return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`
    }

    const props = defineProps({
        type: {
            type: String,
            default: 'info',
            validator: (value) => ['transparent', 'info', 'warning', 'error'].includes(value)
        },
        message: {
            type: String,
            required: true
        },
        inline: {
            type: Boolean,
            default: false
        }
    })

    const typeClass = computed(() => `alert--${props.type}`)
    const formattedMessage = computed(() => marked.parseInline(props.message, { renderer }))

    const icon = computed(() => {
        switch (props.type) {
            case 'warning': return 'exclamation-triangle'
            case 'error': return 'times-circle'
            default: return 'info-circle'
        }
    })
</script>

<template>
    <div class="alert-wrapper" aria-live="polite" aria-atomic="false">
        <div tabindex="0" :class="['alert', 'fade-in', typeClass, { 'alert--inline': props.inline }]">
            <i :class="`fa-solid fa-${icon}`"></i>
            <span class="alert-message" v-html="formattedMessage"></span>
            <slot />
        </div>
    </div>
</template>

<style scoped>
    .alert-wrapper {
        background-color: var(--color-background-primary);
        position: relative;
        z-index: 9;
    }
    .alert {
        display: flex;
        align-items: center;
        padding: 0.75em 1em;
        border-radius: 0.25rem;
        margin: 0.5em 0;
        transform: translateY(-0.7rem);
        font-size: 0.9rem;
    }
    .alert i {
        margin-right: 0.8rem;
        font-size: 0.9em;
    }
    .alert--transparent {
        background: transparent;
        border-left: 4px solid transparent;
        color: var(--color-text-faded);
        border-bottom: 0.05rem solid var(--color-toolbar-border);
        border-radius: 0;
        padding-bottom: 1.4rem;
    }
    .alert--info {
        border-left: 0.25rem solid #2196f3;
        background: #2195f32f;
    }
    .alert--warning {
        border-left: 4px solid #ff9800;
        background: #ff99032f;
    }
    .alert--error {
        border-left: 4px solid #f44336;
        background: #f443332f;
    }
    .alert--inline {
        transform: translateY(0);
    }
</style>
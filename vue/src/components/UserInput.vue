<script setup>
    import { ref, onMounted, onBeforeUnmount, nextTick, watch, getCurrentInstance } from 'vue'

    const userInput = ref('')
    const textarea = ref(null)
    const maxHeight = 258 // 190 for 7 lines

    const emit = defineEmits(['send', 'adjust-css', 'toggle-alt-assistant'])
    const props = defineProps({
        disabled: {
            type: Boolean,
            required: false,
            default: false
        },
        fixed: {
            type: Boolean,
            required: false,
            default: false
        },
        showAssistantToggle: {
            type: Boolean,
            required: false,
            default: false
        },
        hasFiles: {
            type: Boolean,
            required: false,
            default: false
        }
    })

    watch(() => props.fixed, (newVal) => {
        if (newVal == false) {
            emit('adjust-css', {
                type: 'reset',
                fixed: false
            })
        }
    })

    function setUserInput(value) {
        userInput.value = value
        nextTick(() => {
            emitTextareaResize()
        })
    }

    function clearUserInput() {
        userInput.value = ''
        nextTick(() => {
            emitTextareaResize()
        })
    }

    function getTextareaHeight() {
        if (!textarea.value) return 0
        return Math.min(maxHeight, textarea.value.scrollHeight + 2)
    }

    defineExpose({
        setUserInput,
        clearUserInput,
        getTextareaHeight
    })

    function onSubmit() {
        if (userInput.value.trim() !== '') {
            emit('send', userInput.value) // Preserve line breaks for markdown
            userInput.value = ''

            nextTick(() => {
                // Emit resize after input is cleared so parent can update container height
                if (textarea.value) {
                    textarea.value.style.height = 'auto'
                    let height = Math.min(maxHeight, textarea.value.scrollHeight + 2)
                    emit('adjust-css', {
                        type: 'resize',
                        height,
                        fixed: props.fixed
                    })
                }
                emit('adjust-css', {
                    type: 'submit',
                    fixed: props.fixed
                })
                clearInterval(cycleInterval)
                clearInterval(typingInterval)
                placeholder.value = ""
            })
        }
    }

    function handleKeydown(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            onSubmit();
        }
        // Shift+Enter will insert a newline by default
    }

    const emitTextareaResize = () => {
        if (!textarea.value) return
        textarea.value.style.height = 'auto'
        let height = Math.min(maxHeight, textarea.value.scrollHeight + 2)
        textarea.value.style.height = height + 'px'
        emit('adjust-css', {
            type: 'resize',
            height,
            fixed: props.fixed
        })
    }

    const useAltAssistant = ref(false)
    watch(useAltAssistant, (newVal) => {
        emit('toggle-alt-assistant', newVal)
    })

    /* Placeholder typing effect */

    const suggestions = ref([])

    const placeholder = ref(suggestions.value[0])
    let suggestionIndex = 0
    let typingInterval = null
    let cycleInterval = null

    function typePlaceholder(text) {
        let i = 0
        placeholder.value = ""
        clearInterval(typingInterval)
        typingInterval = setInterval(() => {
            if (i < text.length) {
                placeholder.value += text[i]
                i++
            } else {
                clearInterval(typingInterval)
            }
        }, 50)
    }

    function cyclePlaceholder() {
        suggestionIndex = (suggestionIndex + 1) % suggestions.value.length
        typePlaceholder(suggestions.value[suggestionIndex])
    }

    onMounted(() => {
        // Get placeholders from global config
        const instance = getCurrentInstance()
        const config = instance.appContext.config.globalProperties.$config
        suggestions.value = !!config?.predefinedQuestions ? config.predefinedQuestions : []
        // Shuffle suggestions except the first one
        if (suggestions.value.length > 1) {
            const first = suggestions.value[0]
            const rest = suggestions.value.slice(1)
            for (let i = rest.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1))
                ;[rest[i], rest[j]] = [rest[j], rest[i]]
            }
            suggestions.value = [first, ...rest]
        }

        // If no predefined questions, use default suggestions
        if (suggestions.value.length === 0)
            return

        cycleInterval = setInterval(cyclePlaceholder, 4000 + suggestions.value[suggestionIndex].length * 50)
        typePlaceholder(suggestions.value[0])
    })

    onBeforeUnmount(() => {
        clearInterval(cycleInterval)
        clearInterval(typingInterval)
    })
</script>

<template>
    <form class="user-input-form" @submit.prevent="onSubmit">
        <textarea
            ref="textarea"
            :placeholder="placeholder"
            v-model="userInput"
            :disabled="props.disabled"
            class="user-input"
            rows="1"
            @keydown="handleKeydown"
            @input="emitTextareaResize"
        />
        <button type="submit" :disabled="userInput.trim() === ''">
            <i class="fa-solid fa-paper-plane"></i>
        </button>
            
        <div v-if="props.showAssistantToggle"
            :class="['alt-assistant-toggle', { 'landing-page': !props.fixed, 'has-files': props.hasFiles }]">
            <label class="switch" for="checkbox">
                <input type="checkbox" id="checkbox" v-model="useAltAssistant"  />
                <div class="slider round"></div>
            </label>
            <div>Søg på internettet</div>
        </div>
    </form>

</template>

<style scoped>
    form {
        position: relative;
        display: flex;
        align-items: center;
        padding-left: 0.8rem;
        padding-right: 0.8rem;
    }
    .user-input {
        width: 100%;
        padding: 1rem;
        padding-left: 2.5rem;
        padding-right: 3rem;
        font-size: 1rem;
        border-radius: 2rem;
        resize: none;

        border: 0.05rem solid var(--color-input-border);
        color: var(--color-text-primary);
        background-color: var(--color-input-background);
        transition: background-color 0.2s ease, border 0.2s ease-in-out;
        box-shadow: var(--box-shadow-input);
        resize: none;
        outline: none;
        font-family: inherit;
        scrollbar-width: thin;
        scrollbar-color: var(--color-code-border) transparent;
        overflow-y: auto;
        overflow-x: hidden;
    }
    /* .user-input::-webkit-scrollbar {
        width: 0.5rem;
        background: transparent;
    }
    .user-input::-webkit-scrollbar-thumb {
        background: #444;
        border-radius: 0.3rem;
    }
    .user-input::-webkit-scrollbar-track {
        background: blue;
    }
    .user-input::-webkit-scrollbar-thumb:hover {
        background: #666;
    } */

    .user-input::placeholder {
        color: var(--color-input-placeholder);
        text-wrap: nowrap;
        overflow: hidden;
        white-space: nowrap;
    }
    .user-input:focus {
        background-color: var(--color-input-background-focus);
    }
    button[type="submit"] {
        position: absolute;
        right: 0;
        transform: translateX(-1.4rem);
        width: 2.3rem;
        height: 2.3rem;
        border-radius: 100%;
        border: 0;
        background-color: var(--color-input-button-submit);
        color: var(--color-text-faded);
        transition: background-color 0.2s;
    }
    button[type="submit"]:disabled {
        pointer-events: none;
    }
    button[type="submit"]:not(:disabled):hover {
        cursor: pointer;
        background-color: var(--color-input-button-submit-hover);
        color: var(--color-text-primary);
    }

    .alt-assistant-toggle {
        width: max-content;
        position: absolute;
        display: flex;
        align-items: center;
        padding-right: 0.5rem;
        padding-left: 1.5rem;
        padding-top: 0.5rem;
        border-top-left-radius: 0.5rem;
        gap: 1rem;
        font-size: 0.9rem;
        color: var(--color-text-faded);
        z-index: 1;
        transition: color 0.2s;
        background-color: var(--color-background-primary);
    }
    .alt-assistant-toggle:has(input:checked) {
        color: var(--color-text-primary);
    }
    .alt-assistant-toggle.landing-page {
        bottom: -5rem;
        left: 50%;
        transform: translateX(-50%);
    }
    @media screen and (max-width: 360px) { /* Adjust position for very small screens */
        .alt-assistant-toggle.landing-page {
            top: -15rem;
            bottom: auto;
        }
    }
    .alt-assistant-toggle.landing-page.has-files {
        transform: translate(-50%, 2rem);
    }
    .alt-assistant-toggle:not(.landing-page) {
        bottom: 4.5rem;
        right: 1rem;
    }

    .switch {
        display: inline-block;
        height: 2rem; /* 34px */
        position: relative;
        width: 3.75rem; /* 60px */
    }
    .switch input {
        display: none;
    }
    .slider {
        background-color: var(--color-input-background);
        outline: 0.05rem solid var(--color-input-border);
        bottom: 0;
        cursor: pointer;
        left: 0;
        position: absolute;
        right: 0;
        top: 0;
        transition: 200ms;
    }
    .slider:before {
        background-color: var(--color-button-text);
        bottom: 0.25rem; /* 4px */
        content: "";
        height: 1.5rem; /* 24px */
        left: 0.25rem; /* 4px */
        position: absolute;
        transition: 200ms;
        width: 1.5rem; /* 24px */
    }
    .slider:hover:before {
        background-color: var(--color-button-text-hover);
    }
    input:checked + .slider {
        background-color: var(--color-button-green-hover);
        outline: 0.05rem solid var(--color-button-green-border-hover);
    }
    input:checked + .slider:before {
        transform: translateX(1.750rem); /* 28px */
    }
    .slider.round {
        border-radius: 2rem; /* 32px */
    }
    .slider.round:before {
        border-radius: 50%;
    }
</style>
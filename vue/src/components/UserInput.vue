<script setup>
    import { ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'

    const userInput = ref('')
    const textarea = ref(null)
    const maxHeight = 258 // 190 for 7 lines

    const emit = defineEmits(['send', 'adjust-css'])
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

    /* Placeholder typing effect */

    const suggestions = [
        "Fortæl mig hvad du kan hjælpe med",
        "Hvordan opretter jeg en IT supportsag?",
        "Hvad må jeg bruge AI til?",
        "Hvordan opsætter jeg min email på mobilen?",
        "Hvor kan jeg finde interne retningslinjer?",
        "Hjælp mig med at skrive en email til en leverandør",
        "Forklar forskellen på SBSYS og NemSag"
    ]

    const placeholder = ref(suggestions[0])
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
        suggestionIndex = (suggestionIndex + 1) % suggestions.length
        typePlaceholder(suggestions[suggestionIndex])
    }

    onMounted(() => {
        cycleInterval = setInterval(cyclePlaceholder, 4000 + suggestions[suggestionIndex].length * 50)
        typePlaceholder(suggestions[0])
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
        min-height: 3.56rem;
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
</style>
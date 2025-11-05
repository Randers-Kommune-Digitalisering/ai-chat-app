<script setup>
    import { nextTick, ref } from 'vue'
    import { marked } from 'marked'
    import { sendFeedback } from '../services/backend-service.js'

    // Configure marked to treat single line breaks as <br>
    marked.setOptions({ breaks: true })

    const props = defineProps({
        id: {
            type: String,
            required: true,
            default: null
        },
        message: {
            type: Object,
            required: true
        },
        sender: {
            type: String,
            required: true
        },
        references: {
            type: Array,
            required: false,
            default: () => []
        },
        files : {
            type: Array,
            required: false,
            default: () => []
        },
        timeSpent: {
            type: Number,
            required: false,
            default: 0
        }
    })

    const REFERENCE_DISPLAY_LIMIT = 2
    const showAllReferences = ref(false)

    const recentlyCopied = ref(false)

    const copyTextToClipboard = (text) => {
        navigator.clipboard.writeText(text).then(() => {
            console.log('Text copied to clipboard:', text)
            recentlyCopied.value = true
            setTimeout(() => {
                recentlyCopied.value = false
            }, 1500)
        }).catch(err => {
            console.error('Could not copy text: ', err)
        })
    }

    const feedbackLiked = ref(false)
    const feedbackDialogOpen = ref(false)
    const feedbackSent = ref(false)
    const feedbackTextareaRef = ref(null)
    const feedbackText = ref('')

    // Send feedback to backend
    async function submitFeedback() {
        if (!feedbackText.value.trim()) return;
        // Prepare chat history for backend (only content)
        let chatHistory = [];
        chatHistory.push({ content: props.message.content });
        // If you have full chat history in parent, pass as prop and use that instead
        try {
            const data = await sendFeedback(feedbackText.value, props.id, chatHistory);
            if (data.success) {
                feedbackSent.value = true;
                feedbackDialogOpen.value = false;
            } else {
                alert('Kunne ikke sende feedback: ' + (data.message || 'Ukendt fejl'));
            }
        } catch (err) {
            alert('Fejl ved afsendelse af feedback: ' + err);
        }
    }

    const resizeTextareaToFitContent = () => {
        let maxHeight = 218 // pixels = 10 lines
        feedbackTextareaRef.value.style.height = 'auto'
        let height = Math.min(maxHeight, feedbackTextareaRef.value.scrollHeight + 2) + 'px'
        feedbackTextareaRef.value.style.height = height
    }
    function scrollToFeedbackDialog() {
        if (feedbackDialogOpen.value == false) return

        nextTick(() => {
            const item = document.getElementById('feedback_' + props.id)
            if (item) {
                let rect = item.getBoundingClientRect()
                let margin = 128 // fixed margin from bottom = height of input box
                let scrollAmount = 0
                if (rect.bottom > window.innerHeight - margin) {
                    scrollAmount = rect.bottom - (window.innerHeight - margin)
                }
                window.scrollBy({
                    left: 0, top: scrollAmount,
                    behavior: "smooth"
                })
            }
            const textarea = document.getElementById('feedback_textarea_' + props.id)
            if (textarea) textarea.focus()
        })
    }

</script>

<template>
    <div :class="['chat-message', props.sender]" :id="props.id">
        <div class="chat-content" v-html="marked(props.message.content)"></div>

        <div v-if="props.sender == 'user'">
            <div class="fileUploads" v-if="props.files.length > 0">
                <div
                    v-for="(file, index) in props.files"
                    :key="index"
                    class="file-upload-item"
                >
                    <i class="fa-regular fa-file"></i>
                    {{ file.name }}
                </div>
            </div>
        </div>

        <div v-if="props.sender == 'assistant'">

            <div class="references">
                <div
                    v-if="props.references.length > 0"
                    v-for="(ref, index) in props.references.slice(0, showAllReferences ? props.references.length : REFERENCE_DISPLAY_LIMIT)"
                    :key="index">
                    <a :href="ref.link" target="_blank" rel="noopener">{{ ref.title }}</a>
                </div>
                <div v-if="props.references.length > REFERENCE_DISPLAY_LIMIT" class="show-more-less">
                    <a href="#" @click.prevent="showAllReferences = !showAllReferences">
                        <template v-if="showAllReferences"><i class="fa-solid fa-arrow-left"></i></template>
                        <template v-else><i class="fa-solid fa-plus"></i>{{ props.references.length - REFERENCE_DISPLAY_LIMIT }}</template>
                    </a>
                </div>

                <div class="timer">
                    <i class="fa-regular fa-clock"></i>
                    {{ props.timeSpent }} sekunder
                </div>
            </div>

            <div class="options">
                <div class="option" @click="copyTextToClipboard(props.message.content)">
                    <i class="fa-regular fa-copy"></i>
                    <div class="tooltip">{{ recentlyCopied ? 'Kopieret!' : 'Kopiér svar' }}</div>
                </div>
                <div :class="['option', { disabled: feedbackLiked }]" @click="feedbackLiked = !feedbackLiked">
                    <i :class="[feedbackLiked ? 'fa-solid' : 'fa-regular', 'fa-thumbs-up']"></i>
                    <div class="tooltip">Synes godt om</div>
                </div>
                <div :class="['option', { disabled: feedbackSent }]" @click="feedbackDialogOpen = !feedbackDialogOpen; scrollToFeedbackDialog()">
                    <i :class="[feedbackDialogOpen || feedbackSent ? 'fa-solid' : 'fa-regular', 'fa-thumbs-down']"></i>
                    <div class="tooltip">Giv feedback</div>
                </div>
                <div v-if="feedbackSent" class="feedback-sent-message">
                    Tak for din feedback!
                </div>
            </div>

            <div class="feedback-dialog" :id="'feedback_' + props.id" v-if="feedbackDialogOpen" tabindex="-1">
                <textarea
                    v-model="feedbackText"
                    ref="feedbackTextareaRef"
                    :id="'feedback_textarea_' + props.id"
                    @input="resizeTextareaToFitContent"
                    :placeholder="'Giv din feedback til svaret her ...\n\nOBS: Samtale og feedback gemmes til analytiske formål.'"
                    class="feedback-textarea"
                    rows="3"
                ></textarea>
                <div class="submit-feedback-button-container">
                    <button
                        class="submit-feedback-button"
                        @click="submitFeedback"
                        :disabled="!feedbackText.trim()">
                        Send feedback
                    </button>
                    <button class="cancel-feedback-button" @click="feedbackDialogOpen = false">
                        Annuller
                    </button>
                </div>
            </div>  
        </div>
    </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@300..700&display=swap');
    .chat-message {
        margin-bottom: 0.5rem;
        padding-top: 1rem;
        padding-bottom: 1rem;
        font-size: 1rem;
    }
    .chat-message.user {
        background-color: var(--color-chat-user-background);
        border: 0.05rem solid var(--color-chat-user-border);
        margin-left: auto;
        max-width: 100%;
        justify-self: flex-start;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
        border-radius: 0.6rem;
    }

    .chat-content {
        word-wrap: break-word;
    }
        :deep(.chat-content > *:first-child) {
            margin-top: 0;
            margin-block-start: 0rem;
        }
        :deep(.chat-content > *:last-child) {
            margin-bottom: 0;
            margin-block-end: 0rem;
        }
        :deep(.chat-content code) {
            display: inline-block;
            background-color: var(--color-code-background);
            padding: 0.2rem 0.4rem;
            border-radius: 0.3rem;
            font-family: var(--font-code);
            border: 0.05rem solid var(--color-code-border);
            font-size: 0.8em;
        }

    .fileUploads {
        padding-top: 0.3rem;
        transform: translateY(0.2rem);
        display: flex;
        flex-direction: row;
        flex-wrap: wrap-reverse;
        gap: 0.8rem;
    }
    .fileUploads div {
        background-color: var(--color-options-background-hover);
        border-radius: 0.5rem;
        padding: 0.4rem 0.8rem;
        font-size: 0.8rem;
        color: var(--color-text-primary);
        user-select: none;
        transition: background-color 0.3s, color 0.2s;
    }
    .fileUploads div i {
        width: 0.6rem;
        margin-right: 0.4rem;
        font-size: 0.8em;
    }

    /* .chat-message .assistant {
    } */

    /* .chat-message:last-child {
        margin-bottom: 2rem;
    } */

    .references {
        margin-top: 2rem;
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
    }
    .references a {
        display: inline-block;
        width: fit-content;
        user-select: none;

        color: var(--color-reference-text);
        font-size: 0.85rem;
        text-decoration: none;

        padding: 0.5rem 1rem;
        border-radius: 5rem;
        
        background-color: var(--color-reference-background);
        transition: background-color 0.3s, color 0.2s;
    }
    .references a:hover {
        color: var(--color-reference-text-hover);
        background-color: var(--color-reference-background-hover);
    }
    .references .time-spent {
        display: inline-block;
        font-family: var(--font-code);
        color: var(--color-text-gray);
        font-size: 0.7em;
        display: flex;
        align-items: center;
        padding-left: 1rem;
    }
    .time-spent .fa-clock {
        font-size: 0.8em;
    }

    .timer {
        margin-left: 0.5rem;
        font-family: var(--font-code);
        color: var(--color-text-gray);
        font-size: 0.7em;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    .timer .fa-clock {
        font-size: 0.8em;
        transform: translateY(0.05rem);
    }

    .options {
        margin-top: 1rem;
        padding-left: 1rem;
        display: flex;
        color: var(--color-options-text);
    }
    .option {
        position: relative;
        transition: color 0.2s;
        background-color: transparent;
        padding: 0.3rem 0.6rem;
        border-radius: 0.4rem;
    }
        .option.disabled {
            pointer-events: none;
            color: var(--color-options-text-selected);
        }
        .option:hover {
            cursor: pointer;
            color: var(--color-options-text-selected);
            background-color: var(--color-options-background-hover);
        }
    .show-more-less * {
        color: var(--color-reference-more) !important;
    }    
    .show-more-less:hover * {
        color: var(--color-reference-more-hover) !important;
    }
    .show-more-less > a {
        display: flex;
        gap: 0.3rem;
        align-items: center;
        height: 100%;
    }
    .show-more-less i {
        font-size: 0.7em;
    }
    .option .tooltip {
        bottom: -100%;
        left: 50%;
        transform: translateX(-50%);
    }
    .feedback-sent-message {
        margin-left: 0.5rem;
        font-size: 0.9rem;
        align-self: center;
    }

    .feedback-dialog {
        margin-top: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        max-width: 100%;
    }
    .feedback-dialog > textarea {
        width: 100%;
        padding: 0.5rem;
        border-radius: 0.4rem;
        border: 0.05rem solid var(--color-input-border);
        background-color: var(--color-input-background);
        color: var(--color-text-primary);
        font-family: inherit;
        font-size: 0.9rem;
        outline: none;
        resize: none;
        transition: background-color 0.2s;
    }
    .feedback-dialog > textarea:focus {
        background-color: var(--color-input-background-focus);
    }
    .feedback-dialog > .submit-feedback-button-container {
        display: flex;
        gap: 0.5rem;
        justify-content: flex-end;
    }
    .feedback-dialog > textarea::placeholder {
        color: var(--color-input-placeholder);
    }
        .submit-feedback-button, .cancel-feedback-button {
            align-self: flex-end;
            padding: 0.8rem 1rem;
            border: none;
            border-radius: 0.4rem;
            font-size: 0.9rem;
            cursor: pointer;
            transition: background-color 0.2s ease, color 0.2s ease;
            color: var(--color-button-text);
        }
        .submit-feedback-button {
            background-color: var(--color-button-green);
            border: 0.05rem solid var(--color-button-green-border);
        }
        .submit-feedback-button:not(:disabled):hover {
            background-color: var(--color-button-green-hover);
            border: 0.05rem solid var(--color-button-green-border-hover);
            color: var(--color-button-text-hover);
        }
        .submit-feedback-button:disabled {
            background-color: var(--color-button-green-disabled);
            border: 0.05rem solid var(--color-button-green-disabled-border);
            cursor: default;
            color: var(--color-button-green-disabled-text);
        }
        .cancel-feedback-button {
            background-color: var(--color-button-gray);
            border: 0.05rem solid var(--color-button-gray-border);
            color: var(--color-button-text);
        }
        .cancel-feedback-button:hover { 
            background-color: var(--color-button-gray-hover);
            border: 0.05rem solid var(--color-button-gray-border-hover);
            color: var(--color-button-text-hover);
        }

    @media screen and (min-width: 600px) {
        .chat-message.user {
            max-width: 40.5rem;
        }
        .feedback-dialog {
            max-width: 40.5rem;
        }
    }
    @media screen and (min-width: 875px)  {
        .chat-message.user {
            max-width: 75%;
        }
        .feedback-dialog {
            max-width: 75%;
        }
    }
</style>
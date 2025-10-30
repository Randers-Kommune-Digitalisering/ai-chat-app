<script setup>
    import { ref, nextTick } from 'vue'
    import UserInput from '../components/UserInput.vue'
    import FileUpload from '../components/FileUpload.vue'
    import ChatMessageItem from '../components/ChatMessage.vue'
    import Alert from '../components/Alert.vue'
    import { startThread, sendMessage } from '../services/backend-demo.js'

    class ChatMessage {
        constructor(sender, content, references = [], files = [], timeSpent = 0) {
            this.sender = sender
            this.content = content
            this.references = references
            this.files = files
            this.timeSpent = timeSpent
        }
    }
    class Reference {
        constructor(title, link) {
            this.title = title
            this.link = link
        }
    }
    class File {
        constructor(details, content) {
            this.details = details
            this.content = content
        }
    }

    const threadId = ref(null)
    const userInput = ref(null)
    const userFiles = ref([])
    const chatMessages = ref([])
    const awaitingResponse = ref(false)

    async function clearChat() {
        // Clear UI state
        chatMessages.value = []
        awaitingResponse.value = false
        threadId.value = null
        userInput.value.clearUserInput()
        clearAllFiles()
        stopTimer()

        // start new thread
        threadId.value = await startThread()
        if (!threadId.value) {
            console.error("Failed to start new thread.")
        }
    }

    defineExpose({
        clearChat,
        chatMessages
    })

    // Handle user input
    async function onUserInput(message) {
        const files = userFiles.value.map(file => ({ name: file.details.name, content: file.content }))
        await addChatMessage(message, files)
        clearAllFiles()
    }

    async function addChatMessage(message, files) {
        // Add user message to state
        const newMessage = new ChatMessage('user', message, [], files)
        chatMessages.value.push(newMessage)
        nextTick(() => {
            updateInputPadding()
            scrollToMessage(chatMessages.value.length - 1)
            startTimer()
        })

        // Send message to backend
        awaitingResponse.value = true
        const { response, references } = await sendMessage(threadId.value, message, files)

        // Response received from backend
        console.log("Backend response:", response, references)
        const timeSpent = Number((stopTimer() / 1000).toFixed(2)) // seconds, rounded to 2 decimals
        const assistantMessage = new ChatMessage(
            'assistant',
            response,
            references.map(ref => new Reference(ref.title, ref.link)),
            [],
            timeSpent
        )

        // Update state
        chatMessages.value.push(assistantMessage)
        awaitingResponse.value = false

        // Update UI
        nextTick(() => {
            updateInputPadding()
            const input = document.querySelector('.user-input')
            if (input) input.focus()
            scrollToMessage(chatMessages.value.length - 1)
        })
    }

    // Handle file uploads
    const fileUploader = ref(null)
    function onFilesDropped(files) {
        for (let file of files) {
            console.log("File dropped:", file)
            const fileDetails = new fileUploader.value.FileDetails(file.name, file.size, file.type)
            userFiles.value.push(new File(fileDetails, file.content))
        }
    }
    function onFileRemoved(fileDetails) {
        const index = userFiles.value.findIndex(file => file.details.name === fileDetails.name && file.details.size === fileDetails.size)
        if (index > -1) {
            userFiles.value.splice(index, 1)
        }
        else
        {
            console.warn("File to remove not found in userFiles.")
        }
    }
    function onFileUploadAdjustCss() {
        nextTick(() => {
            updateInputPadding()
        })
    }
    function updateInputPadding() {
        // Always get the latest textarea height from UserInput
        const height = userInput.value?.getTextareaHeight?.() || 0
        onAdjustCss({ type: 'resize', height, fixed: chatMessages.value.length > 0 })
    }
    function clearAllFiles() {
        fileUploader.value.clearFiles()
        userFiles.value = []
    }

    // Scroll to specific message
    function scrollToMessage(index) {
        const item = document.getElementById('msg_' + index)
        if (item) {
            let rect = item.getBoundingClientRect()
            let calc = rect.top - 8 - 56 // 8px offset from top + 56px header height

            window.scrollBy({
                left: 0, top: calc,
                behavior: "smooth"
            })
        }
    }

    // Timer
    const timeSpent = ref(0)
    let startTime = 0
    let animationFrameId = null

    function updateTimer() {
        timeSpent.value = Date.now() - startTime
        animationFrameId = requestAnimationFrame(updateTimer)
    }
    function startTimer() {
        startTime = Date.now()
        animationFrameId = requestAnimationFrame(updateTimer)
    }
    function stopTimer() {
        let elapsed = Date.now() - startTime
        cancelAnimationFrame(animationFrameId)
        timeSpent.value = 0
        return elapsed
    }

    // Handle CSS adjustments
    // Sets the app padding based on UserInput height and mode (fixed or landing)
    // Sets the position of the user input container
    const userInputContainer = ref(null)
    function onAdjustCss(payload) {
        // payload: { type, height (of userInputContainer), fixed }
        if (!userInputContainer.value) return
        const inputContainer = userInputContainer.value
        const app = document.getElementById('app')
        const fileContainer = document.getElementById('file-uploads')
        if (payload.type === 'resize') {
            // Adjust textarea container position and app padding
            if (payload.fixed) {
                // Fixed mode: adjust app padding
                if (app) {
                    // Add height of  file uploader if visible
                    const fileUploaderHeight = fileContainer.offsetHeight
                    const padding = Math.max(payload.height / 16 + 3, 6) + fileUploaderHeight / 16 + 0.5
                    app.style.paddingBottom = padding + 'rem'
                }
                inputContainer.style.bottom = '0rem'
            } else {
                // Landing page: position container vertically and offset by textarea height
                const heightPx = payload.height || 0
                inputContainer.style.bottom = `calc(50% - ${heightPx}px - 3rem + 57px)`
                if (app) app.style.paddingBottom = '10rem'
            }
        } else if (payload.type === 'reset') {
            // Reset to landing page position
            inputContainer.style.bottom = `calc(50% - 3rem)`
            if (app) app.style.paddingBottom = '10rem'
        } else if (payload.type === 'submit') {
            // After submit, move to bottom
            inputContainer.style.bottom = '0rem'
            if (app) app.style.paddingBottom = '6rem'
        }
    }
</script>

<template>
    <Alert
        v-if="chatMessages.length == 0"
        type="transparent"
        message="Velkommen! Start en samtale ved at skrive en besked nedenfor. Du kan også uploade filer for at give mere kontekst."
    />
    <Alert
        v-else
        type="warning"
        message="Husk at undgå at dele personfølsomme oplysninger i samtalen."
    />
    
    <div class="welcome-header" v-if="chatMessages.length == 0">
        Hej, hvad kan jeg hjælpe med?
    </div>

    <div style="margin-bottom: auto"></div><!-- spacer to force alerts to top and chat to bottom -->

    <div id="chat-messages">
        <template v-for="(msg, index) in chatMessages" :key="index">
            <ChatMessageItem
                :id="'msg_' + index"
                :message="msg"
                :sender="msg.sender"
                :references="msg.references"
                :files="msg.files"
                :timeSpent="msg.timeSpent"
            />
        </template>

        <div v-if="awaitingResponse" class="loading-indicator">
            <i class="fa-solid fa-rotate rotate"></i>
            Assistenten tænker ...
            <span class="timer">
                <i class="fa-regular fa-clock"></i>
                {{ (timeSpent / 1000).toFixed(2) }}
            </span>
        </div>
    </div>

    <div :class="['user-input-container', { 'landing-page': chatMessages.length == 0 }]" ref="userInputContainer">
        <UserInput
            ref="userInput"
            @send="onUserInput"
            :disabled="awaitingResponse"
            :fixed="chatMessages.length > 0"
            @adjust-css="onAdjustCss"
        />

        <FileUpload
            ref="fileUploader"
            @files-dropped="onFilesDropped"
            @file-removed="onFileRemoved"
            @file-upload-adjust-css="onFileUploadAdjustCss" />
    </div>
</template>

<style scoped>
    .welcome-header {
        position: absolute;
        font-size: 1.6rem;
        text-align: center;
        left: 50%;
        bottom: 50%;
        transform: translate(-50%, -4.5rem);
        z-index: 3;
    }
    .loading-indicator
    {
        font-style: italic;
        color: var(--color-options-text-selected);
        margin-bottom: 2rem;
        padding: 1rem;
    }
        .loading-indicator .fa-rotate {
            margin-right: 0.5rem;
            font-size: 0.9em;
        }
        .loading-indicator .timer {
            margin-left: 0.5rem;
            font-family: var(--font-code);
            color: var(--color-text-gray);
            font-size: 0.7em;
        }
            .timer .fa-clock {
                font-size: 0.8em;
            }
    .user-input-container {
        position: fixed;
        bottom: 0rem;
        padding-bottom: 2rem;
        padding-top: 1rem;
        left: 50%;
        transform: translateX(-50%);
        width: 100%;
        background-color: var(--color-background-primary);
    }
        .user-input-container.landing-page {
            bottom: calc(50% - 3rem); /* Overwritten by UserInput.vue when not fixed */
        }
    @media screen and (min-width: 875px) {
        .user-input-container  {
            max-width: 56rem;
        }
    }

    .rotate {
        animation: l24 1.5s infinite linear;
    }
    @keyframes l24 {
        100% {transform: rotate(1turn)}
    }
</style>
<script setup>
    import { ref, nextTick, getCurrentInstance, onMounted, onUnmounted, watch } from 'vue'
    import UserInput from '../components/UserInput.vue'
    import FileUpload from '../components/FileUpload.vue'
    import ChatMessageItem from '../components/ChatMessage.vue'
    import Alert from '../components/Alert.vue'
    import { startThread, sendThreadMessage, sendChatMessage, getIllegalContents, fetchConversationByPermit } from '../services/backend-service.js'
    import { portalDebugLog, notifyParentLoaded, notifyParentNewConversation, notifyParentChatCleared } from '../utils/portalMessaging.js'

    const props = defineProps({
        userEmail: { type: String, default: null }
    })


    class ChatMessage {
        constructor(sender, content, illegalContents = [], references = [], files = [], timeSpent = 0) {
            this.sender = sender
            this.content = content
            this.illegalContents = illegalContents
            this.redactedContents = illegalContents.slice() // Preserve original filtered content for later restoration when unfiltering assistant responses
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

    const isAgent = ref(false)
    const threadId = ref(null)
    const activeConversationId = ref(null)
    const currentUserEmail = ref(props.userEmail)
    const userInput = ref(null)
    const userFiles = ref([])
    const chatMessages = ref([])
    const awaitingResponse = ref(false)
    const awaitingUserInput = ref(false)
    const showAssistantToggle = ref(false)
    const useAltAssistant = ref(false)
    const altAssistantAlertType = ref('info')
    const altAssistantAlertMsg = ref('')
    const ASSISTANT_NAME_ID = ref('')
    const assistantName = ref('')
    const assistantDescription = ref('')
    const errorMessage = ref('')
    const errorTimeoutId = ref(null)

    onMounted(() => {
        const instance = getCurrentInstance()
        const config = instance.appContext.config.globalProperties.$config
        isAgent.value = !!config?.isAgent
        showAssistantToggle.value = !!config?.showAssistantToggle
        altAssistantAlertMsg.value = config?.altAlertMsg
        altAssistantAlertType.value = config?.altAlertType
        ASSISTANT_NAME_ID.value = config?.assistantNameId || ''
        assistantName.value = config?.assistantName || ''
        assistantDescription.value = config?.description || ''
    })

    watch(
        () => props.userEmail,
        (next) => {
            if (next) currentUserEmail.value = next
        },
        { immediate: true }
    )

    watch(errorMessage, (val) => {
        // Clear any existing timeout before starting a new one
        if (errorTimeoutId.value !== null) {
            clearTimeout(errorTimeoutId.value)
            errorTimeoutId.value = null
        }

        if (val) {
            errorTimeoutId.value = setTimeout(() => {
                errorMessage.value = ''
                errorTimeoutId.value = null
            }, 10000)
        }
    })

    onUnmounted(() => {
        if (errorTimeoutId.value !== null) {
            clearTimeout(errorTimeoutId.value)
            errorTimeoutId.value = null
        }
    })

    defineExpose({
        clearChat,
        loadConversation,
        activeConversationId,
        chatMessages
    })

    async function clearChat(options = {}) {
        const { notifyParent = true } = options
        const previousConversationId = activeConversationId.value
        // Clear UI state
        chatMessages.value = []
        awaitingResponse.value = false
        awaitingUserInput.value = false
        threadId.value = null
        activeConversationId.value = null
        useAltAssistant.value = false
        userInput.value.clearUserInput()
        clearAllFiles()
        stopTimer()
        if (notifyParent) {
            notifyParentChatCleared(previousConversationId ? { conversationId: previousConversationId } : {})
        }

        if (!isAgent.value)
                return

        // Start new thread if Agent mode
        threadId.value = await startThread()
        if (!threadId.value)
            console.error("Failed to start new thread.")
    }

    async function loadConversation(permit) {
        portalDebugLog('Loading conversation by permit')
        const data = await fetchConversationByPermit(permit)

        if (data?.success === false) {
            console.error("Failed to load conversation:", data?.message)
            return
        }

        // Process loaded conversation data and update UI accordingly
        if (!data.conversation || !Array.isArray(data.conversation?.messages)) {
            console.error("Invalid conversation data format.")
            return
        }
        await clearChat({ notifyParent: false })
        const loadedConversationId = data?.conversation?.id
        if (loadedConversationId) activeConversationId.value = loadedConversationId

        const loadedUserEmail = data?.conversation?.user_email
        if (loadedUserEmail) currentUserEmail.value = loadedUserEmail
        const loadedThreadId = data.conversation.threadId ?? data.conversation.thread_id
        if (isAgent.value && loadedThreadId) {
            threadId.value = loadedThreadId
            portalDebugLog("Set thread ID to:", threadId.value)
        }

        function mapFiles(msg) {
            const rawFiles = Array.isArray(msg?.files) ? msg.files : []
            const rawAttachments = Array.isArray(msg?.attachments) ? msg.attachments : []

            if (rawFiles.length > 0) return rawFiles

            return rawAttachments.map(att => ({
                name: att.file_name ?? att.name ?? 'unknown',
                size: att.file_size ?? att.size ?? 0,
                type: att.file_type ?? att.type ?? 'application/octet-stream',
                // Needed in chat mode so a loaded conversation can be continued
                // with the same document context.
                content: att.file_content
            }))
        }
        function mapReferences(msg) {
            // DB-backed references are shaped like {reference_type, reference_content}.
            // reference_content is JSON stored by backend (see db_controller normalization).
            const raw = Array.isArray(msg?.references) ? msg.references : []
            return raw.map(ref => {
                    const content = ref?.reference_content
                    if (typeof content !== 'string') return null
                    try {
                        const parsed = JSON.parse(content)
                        return new Reference(parsed.title ?? 'Reference', parsed.url ?? '')
                    } catch (_) {
                        return null
                    }
                })
                .filter(Boolean)
        }
        for (let msg of data.conversation.messages) {
            const chatMsg = new ChatMessage(
                msg.sender,
                msg.content,
                msg.illegalContents || [],
                mapReferences(msg),
                mapFiles(msg),
                msg.timeSpent || 0
            )
            chatMessages.value.push(chatMsg)
        }
        notifyParentLoaded()
        nextTick(() => {
            updateInputPadding()
            scrollToMessage(chatMessages.value.length - 1, false)
        })
        portalDebugLog('Loaded conversation data:', data)
    }

    // Handle user input
    async function onUserInput(message) {
        // Only send name/content of files to backend, but keep all file info in userFiles
        await addMessage(message)
    }

    async function addMessage(message) {
        // Filter user message for illegal content
        let illegalContents = []
        try {
            illegalContents = await getIllegalContents(message)
        } catch (error) {
            console.error("Error filtering message:", error)
        }

        // Add user message to state (with all file info for display)
        const newMessage = new ChatMessage('user', message, illegalContents, [], [...userFiles.value])
        clearAllFiles() // Remove all files from UI
        chatMessages.value.push(newMessage)
        nextTick(() => {
            updateInputPadding()
            scrollToMessage(chatMessages.value.length - 1)
        })

        // Send message if no illegal content
        if (illegalContents.length === 0)
            await sendMessage(newMessage)
        else
            awaitingUserInput.value = true
    }

    const undoAndEditMessage = async (chatMessage) => {
        awaitingUserInput.value = false
        // Re-add user files to state
        for (let file of chatMessage.files) {
            addFile(file)
        }
        // Remove last user message
        chatMessages.value.pop()
        nextTick(() => {
            updateInputPadding()
            const input = document.querySelector('.user-input')
            if (input) input.focus()
            scrollToMessage(chatMessages.value.length - 1)
        })
        // Set user input to previous message content
        userInput.value.setUserInput(chatMessage.content)
    }

    const sendMessage = async (chatMessage) => {
        // Update state
        awaitingUserInput.value = false
        chatMessage.illegalContents = [] // Clear illegal contents
        awaitingResponse.value = true
        startTimer()

        // Prepare messages for chat mode
        let message = chatMessage.content
        let messages = []
        if (!isAgent.value) {
            messages = chatMessages.value.map(msg => ({
                role: msg.sender,
                content: msg.content,
                files: msg.files.map(({ name, content }) => ({ name, content }))
            }))
        }
        // Create thread if agent mode and thread does not exists
        else if (!threadId.value) {
            threadId.value = await startThread()
            console.log("Started new thread with ID:", threadId.value)
            if (!threadId.value) {
                console.error("Failed to start new thread.")
                return
            }
        }

        // Send message to backend
        const result = isAgent.value ?
            await sendThreadMessage(
                threadId.value,
                activeConversationId.value,
                message,
                chatMessage.files.map(({ name, content }) => ({ name, content })),
                useAltAssistant.value,
                currentUserEmail.value
            ) :
            await sendChatMessage(activeConversationId.value, messages, currentUserEmail.value)

        // Response received from backend
        const { success, message: backendMessage, response, references, conversation_id, title } = result

        if (success === false) {
            console.error("Backend returned success=false:", backendMessage)
            stopTimer()
            awaitingResponse.value = false
            undoAndEditMessage(chatMessage)
            errorMessage.value = backendMessage || "Der opstod en fejl. Prøv venligst igen."
            nextTick(() => {
                updateInputPadding()
                const input = document.querySelector('.user-input')
                if (input) input.focus()
                scrollToMessage(chatMessages.value.length - 1)
            })
            return
        }

        activeConversationId.value = conversation_id

        if(chatMessages.value.length == 1) // If first message - notify parent of new conversation
            notifyParentNewConversation({ id: conversation_id, gpt_id: ASSISTANT_NAME_ID.value, title: title || 'Ny samtale' })

        const timeSpent = Number((stopTimer() / 1000).toFixed(2)) // seconds, rounded to 2 decimals
        if (!awaitingResponse.value) {
            console.warn("Response received but awaitingResponse is false. Ignoring response.")
            return
        }
        awaitingResponse.value = false
        const assistantMessage = new ChatMessage(
            'assistant',
            unfilterResponseContent(response),
            [],
            (references || []).map(ref => new Reference(ref.title, ref.url)),
            [],
            timeSpent
        )
        if (!response || response.trim() === "") {  // No response
            // Re-add user files to state
            for (let file of chatMessage.files) {
                addFile(file)
            }
            assistantMessage.content = backendMessage || "Beklager, der opstod en fejl. Prøv venligst igen."
        }
        chatMessages.value.push(assistantMessage)

        // Update UI
        nextTick(() => {
            updateInputPadding()
            const input = document.querySelector('.user-input')
            if (input) input.focus()
            scrollToMessage(chatMessages.value.length - 1)
        })
    }

    function unfilterResponseContent(content) {
        // Replace [REDACTED #1] with original user input for display
        let filtered = content
        const regex = /\[REDACTED\s*#\s*(\d+)\]/g
        const unfiltered = filtered.replace(regex, (fullMatch, group1) => {
            // Find the previous user message (before the assistant's response)
            const redactedIndex = parseInt(group1, 10) - 1
            const prevUserMsg = [...chatMessages.value].reverse().find(msg => msg.sender === 'user')
            if (
                prevUserMsg &&
                Array.isArray(prevUserMsg.redactedContents) &&
                redactedIndex >= 0 &&
                redactedIndex < prevUserMsg.redactedContents.length
            ) {
                return prevUserMsg.redactedContents[redactedIndex]
            }
            return fullMatch
        })
        return unfiltered
    }

    // Handle file uploads
    const fileUploader = ref(null)
    function onFileRemoved(fileObj) {
        const index = userFiles.value.findIndex(f => f.name === fileObj.name && f.size === fileObj.size)
        if (index > -1) {
            userFiles.value.splice(index, 1)
        } else {
            console.warn("File to remove not found in userFiles.")
        }
        nextTick(() => {
            updateInputPadding()
        })
    }
    function onClearFiles() {
        userFiles.value = []
    }
    function updateInputPadding() {
        // Always get the latest textarea height from UserInput
        const height = userInput.value?.getTextareaHeight?.() || 0
        onAdjustCss({ type: 'resize', height, fixed: chatMessages.value.length > 0 })
    }
    function clearAllFiles() {
        let removedFiles = [...userFiles.value]
        userFiles.value = []
        return removedFiles
    }
    function addFile(fileObj) {
        userFiles.value.push(fileObj)
        nextTick(() => {
            updateInputPadding()
        })
    }

    // Scroll to specific message
    function scrollToMessage(index, smoothScroll = true) {
        const item = document.getElementById('msg_' + index)
        if (item) {
            let rect = item.getBoundingClientRect()
            let calc = rect.top - 8 - 56 // 8px offset from top + 56px header height

            window.scrollBy({
                left: 0, top: calc,
                behavior: smoothScroll ? "smooth" : "auto"
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
        if (payload.type === 'resize') {
            // Adjust textarea container position and app padding
            if (payload.fixed) {
                // Fixed mode: adjust app padding
                if (app) {
                    // Add height of  file uploader if visible
                    const fileContainer = document.getElementById('file-uploads')
                    let fileUploaderHeight = fileContainer ? fileContainer.offsetHeight : 0
                    const padding = Math.max(payload.height / 16 + 3, 6) + fileUploaderHeight / 16 + 0.5
                    app.style.paddingBottom = padding + 'rem'
                }
                inputContainer.style.bottom = '0rem'
            } else {
                // Landing page: position container vertically and offset by textarea height
                const heightPx = payload.height || 0
                inputContainer.style.bottom = `calc(35% - ${heightPx}px - 3rem + 57px)`
                if (app) app.style.paddingBottom = '1rem'
            }
        } else if (payload.type === 'reset') {
            // Reset to landing page position
            inputContainer.style.bottom = `calc(35% - 3rem)`
            if (app) app.style.paddingBottom = '1rem'
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
        message="**Bemærk**: Det er ikke tilladt at behandle CPR-numre, følsomme / fortrolige [personoplysninger](https://www.datatilsynet.dk/regler-og-vejledning/grundlaeggende-begreber/hvad-er-personoplysninger) eller foretage afgørelser med AI. Almindelige personoplysninger kan blive følsomme eller fortrolige, hvis de sammenkobles."
    />
    <Alert
        v-else
        type="info"
        message="**Bemærk:** Svarene er AI-genererede og kan indeholde forkerte oplysninger. [Læs mere her](https://broen.randers.dk/digitalisering/ai-univers/retningslinjer-for-generativ-ai/#block-b93fc214-c5b4-4b34-9e85-7f7bdb36560e)."
    />
    <Alert
        v-if="useAltAssistant && altAssistantAlertMsg"
        :type="altAssistantAlertType"
        :message="altAssistantAlertMsg"
    />
    <Alert
        v-if="errorMessage"
        type="error"
        :message="errorMessage"
    />

    <div class="welcome-header" v-if="chatMessages.length == 0">
        Hej, hvad kan jeg hjælpe med?
        <div class="assistant-description" style="white-space: pre-line;">{{ assistantDescription }}</div>
    </div>

    <div style="margin-bottom: auto"></div><!-- spacer to force alerts to top and chat to bottom -->

    <div id="chat-messages">
        <template v-for="(msg, index) in chatMessages" :key="index">
            <ChatMessageItem
                :id="'msg_' + index"
                :message="msg.content"
                :highlightedWords="msg.illegalContents"
                :sender="msg.sender"
                :references="msg.references"
                :files="msg.files"
                :timeSpent="msg.timeSpent"
                :chatHistory="chatMessages"
            />
           
            <div v-if="msg.illegalContents.length > 0" class="alert-content-filter">
                <Alert
                    type="warning"
                    :inline="true"
                    message="**Advarsel**: Din besked indeholder potentielt følsomt eller fortroligt indhold. Hvordan vil du fortsætte?"
                >
                    <div class="alert--buttons">
                        <button @click="undoAndEditMessage(msg)">Redigér</button>
                        <button @click="sendMessage(msg)">Anonymisér og send</button>
                    </div>
                </Alert>
            </div>
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
            @toggle-alt-assistant="val => useAltAssistant = val"
            :showAssistantToggle="showAssistantToggle && (chatMessages.length == 0 || chatMessages[chatMessages.length - 1].illegalContents.length == 0)"
            :hasFiles="userFiles.length > 0"
            :disabled="awaitingResponse || awaitingUserInput"
            :fixed="chatMessages.length > 0"
            @adjust-css="onAdjustCss"
        />

        <FileUpload
            ref="fileUploader"
            :files="userFiles"
            :showAssistantTogglePadding="showAssistantToggle && chatMessages.length != 0"
            @add-file="addFile"
            @remove-file="onFileRemoved"
            @clear-files="onClearFiles" />
    </div>
</template>

<style scoped>
    .welcome-header {
        position: absolute;
        font-size: 1.6rem;
        text-align: center;
        left: 50%;
        bottom: 35%;
        width: max-content;
        max-width: 90%;
        transform: translate(-50%, -5rem);
        z-index: 3;
    }
        .welcome-header .title {
            font-size: 1.5rem;
            font-weight: 300;
            margin-bottom: 10dvh;
        }
        @media screen and (max-width: 360px) { /* Adjust position for very small screens */
            .welcome-header  {
                bottom: 3rem !important;
            }
            .welcome-header .title {
                margin-bottom: 20dvh;
            }
        }
            .welcome-header .title .icons {
                display: flex;
                justify-content: center;
                align-items: center;
                gap: 1rem;
                margin-top: 0.5rem;
                font-size: 1rem;
                user-select: none;
                pointer-events: auto;
                pointer-events: all;
                color: var(--color-text-faded);
            }
            .title .icons span {
                transition: color 0.2s ease;
            }
            .title .icons span:hover {
                cursor: default;
                color: var(--color-text-primary);
            }
        .welcome-header .assistant-description {
            margin-top: 1rem;
            margin-bottom: 1rem;
            font-size: 0.9rem;
            color: var(--color-text-faded);
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
            bottom: calc(35% - 3rem); /* Overwritten by UserInput.vue when not fixed */
        }
        @media screen and (max-width: 360px) { /* Adjust position for very small screens */
            .user-input-container.landing-page  {
                bottom: 0rem !important; /* Overwritten by UserInput.vue when not fixed */
            }
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

    .alert-content-filter {
        position: relative;
        z-index: 11 !important;
        transform: translateY(1rem);
    }

    .alert--buttons {
        margin-left: auto;
        width: max-content;
        display: flex;
    }
        .alert--buttons button {
            margin-left: 0.5rem;
            padding: 0.3rem 0.8rem;
            border: 0.05rem solid var(--color-button-gray-border);
            border-radius: 0.25rem;
            background-color: #8a8a8a11;
            color: var(--color-button-text);
            cursor: pointer;
            font-size: 0.9rem;
            min-width: max-content;
            transition: 0.2s;
            padding-top: 0.6rem;
            padding-bottom: 0.6rem;
        }
        .alert--buttons button:hover {
            background-color: #8a8a8a27;
            color: white;
        }
</style>
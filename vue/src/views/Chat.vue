<script setup>
    import { ref, nextTick, getCurrentInstance, onMounted, onUnmounted, watch } from 'vue'
    import UserInput from '../components/UserInput.vue'
    import FileUpload from '../components/FileUpload.vue'
    import ChatMessageItem from '../components/ChatMessage.vue'
    import Alert from '../components/Alert.vue'
    import { startThread, sendThreadMessageStream, sendChatMessage, getIllegalContents, fetchConversationByPermit } from '../services/backend-service.js'
    import { portalDebugLog, notifyParentLoaded, notifyParentNewConversation, notifyParentChatCleared } from '../utils/portalMessaging.js'

    const props = defineProps({
        userEmail: { type: String, default: null }
    })

    const _DEFAULT_ERROR_MESSAGE = "Beklager, der opstod en fejl. Prøv venligst igen."


    class ChatMessage {
        constructor(sender, content, illegalContents = [], references = [], files = [], timeSpent = 0, isStreaming = false) {
            this.sender = sender
            this.content = content
            this.illegalContents = illegalContents
            this.redactedContents = Array.isArray(illegalContents) ? illegalContents.slice() : [] // Preserve original filtered content for later restoration when unfiltering assistant responses
            this.references = references
            this.files = files
            this.timeSpent = timeSpent
            this.isStreaming = isStreaming
        }
    }

    function asCitationObject(value) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) return null
        return value
    }

    function mapApiReferences(references) {
        if (!Array.isArray(references)) return []
        return references.map(ref => asCitationObject(ref)).filter(Boolean)
    }

    function parseDateValue(value) {
        if (!value) return null
        if (value instanceof Date && !Number.isNaN(value.getTime())) return value
        const parsed = new Date(value)
        if (Number.isNaN(parsed.getTime())) return null
        return parsed
    }

    const isAgent = ref(false)
    const threadId = ref(null)
    const activeConversationId = ref(null)
    const currentUserEmail = ref(props.userEmail)
    const userInput = ref(null)
    const userFiles = ref([])
    const chatMessages = ref([])
    const awaitingResponse = ref(false)
    const responseStatus = ref('Assistenten tænker ...')
    const awaitingUserInput = ref(false)
    const showAssistantToggle = ref(false)
    const useAltAssistant = ref(false)
    const altAssistantAlertType = ref('info')
    const altAssistantAlertMsg = ref('')
    const ASSISTANT_NAME_ID = ref('')
    const assistantName = ref('')
    const assistantDescription = ref('')
    const assistantType = ref('chat')
    const errorMessage = ref('')
    const errorTimeoutId = ref(null)
    const conversationCutoffDate = ref(null)
    const agentFileSizeLimit = ref(10 * 1024 * 1024)
    const responseGeneration = ref(0)

    const chatMessagesEl = ref(null)
    const fileUploadRootEl = ref(null)
    const followStreamAutoScroll = ref(true)
    const isProgrammaticScroll = ref(false)
    const liveRegionText = ref('')
    const completedMessageLiveText = ref('')

    onMounted(() => {
        const instance = getCurrentInstance()
        const config = instance.appContext.config.globalProperties.$config
        assistantType.value = (config?.assistantType || (config?.isAgent ? 'agent' : 'chat')).toLowerCase()
        isAgent.value = assistantType.value === 'agent'
        showAssistantToggle.value = !!config?.showAssistantToggle
        altAssistantAlertMsg.value = config?.altAlertMsg
        altAssistantAlertType.value = config?.altAlertType
        ASSISTANT_NAME_ID.value = config?.assistantNameId || ''
        assistantName.value = config?.assistantName || ''
        assistantDescription.value = config?.description || ''
        conversationCutoffDate.value = parseDateValue(config?.conversationLoadCutoffDate)
        agentFileSizeLimit.value = Number(config?.agentFileSizeLimit) || 10 * 1024 * 1024

        adjustChatMessagesPaddingBottom()
        window.addEventListener('resize', onResize)
        window.addEventListener('scroll', onWindowScroll, { passive: true })
    })

    function onWindowScroll() {
        if (!awaitingResponse.value) return
        if (isProgrammaticScroll.value) return
        followStreamAutoScroll.value = false
    }

    function withProgrammaticScroll(callback) {
        isProgrammaticScroll.value = true
        callback()
        requestAnimationFrame(() => {
            isProgrammaticScroll.value = false
        })
    }

    function adjustChatMessagesPaddingBottom() {
        nextTick(() => {
            const chatEl = chatMessagesEl.value
            if (!chatEl) return

            /* Don't change on landing page */
            if (chatMessages.value.length == 0) {
                chatEl.style.paddingBottom = '1.5rem'
                return
            }

            const uploadsEl = fileUploadRootEl.value?.querySelector?.('.fileUploads')
            const uploadsHeight = userFiles.value.length > 0 && uploadsEl
                ? uploadsEl.getBoundingClientRect().height
                : 0

            if (uploadsHeight > 0) {
                const px = Math.round(uploadsHeight)
                chatEl.style.paddingBottom = `calc(1.5rem + ${px}px)`
            } else {
                chatEl.style.paddingBottom = '1.5rem'
            }
        })
    }

    function adjustAltTogglePosition() {
        nextTick(() => {
            const altToggle = userInput.value?.altToggleEl
            const toggleEl = altToggle?.value ?? altToggle
            if (!toggleEl) return

            /* Don't change unless on landing page */
            if (chatMessages.value.length != 0) {
                toggleEl.style.transform = 'translate(0, 0)'
                return
            }

            const uploadsEl = fileUploadRootEl.value?.querySelector?.('.fileUploads')
            const uploadsHeight = userFiles.value.length > 0 && uploadsEl
                ? uploadsEl.getBoundingClientRect().height
                : 0

            if (uploadsHeight > 0) {
                const px = Math.round(uploadsHeight)
                toggleEl.style.transform = `translate(-50%, calc(${px}px))`
            }
            else {
                toggleEl.style.transform = 'translate(-50%, 0)'
            }
        })
    }

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

    let resizeTimeoutId = null

    function onResize() {
        if (resizeTimeoutId !== null) {
            clearTimeout(resizeTimeoutId)
        }
        resizeTimeoutId = setTimeout(() => {
            adjustChatMessagesPaddingBottom()
            resizeTimeoutId = null
        }, 200)
    }
    
    onUnmounted(() => {
        window.removeEventListener('resize', onResize)
        window.removeEventListener('scroll', onWindowScroll)
        if (resizeTimeoutId !== null) {
            clearTimeout(resizeTimeoutId)
            resizeTimeoutId = null
        }
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
        responseGeneration.value += 1
        // Clear UI state
        chatMessages.value = []
        liveRegionText.value = ''
        completedMessageLiveText.value = ''
        awaitingResponse.value = false
        awaitingUserInput.value = false
        threadId.value = null
        activeConversationId.value = null
        useAltAssistant.value = false
        userInput.value.clearUserInput()
        userInput.value.setInputVisibility(true)
        fileUploader.value.setFileUploadVisibility(true)
        clearAllFiles()
        stopTimer()
        if (notifyParent) {
            notifyParentChatCleared(previousConversationId ? { conversationId: previousConversationId } : {})
        }
    }

    async function loadConversation(permit) {
        portalDebugLog('Loading conversation by permit')
        const data = await fetchConversationByPermit(permit)

        if (data?.success === false) {
            console.error("Failed to load conversation:", data?.message)
            errorMessage.value = data?.message
            notifyParentLoaded()
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

        // Extract and set user email and thread ID from the loaded conversation
        const loadedUserEmail = data?.conversation?.user_email
        if (loadedUserEmail) currentUserEmail.value = loadedUserEmail
        const loadedThreadId = data.conversation.threadId ?? data.conversation.thread_id
        if (isAgent.value && loadedThreadId) {
            threadId.value = loadedThreadId
            portalDebugLog("Set thread ID successfully from loaded conversation")
        }

        // Disable chat input for conversations created before the cutoff date
        const conversationCreatedAt = parseDateValue(data?.conversation?.created_at)
        if (conversationCreatedAt && conversationCutoffDate.value && conversationCreatedAt < conversationCutoffDate.value) {
            portalDebugLog("Disabling chat input due to conversation being created before cutoff date")
            userInput.value.setInputVisibility(false)
            fileUploader.value.setFileUploadVisibility(false)
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
            // reference_content stores native citation JSON from backend.
            const raw = Array.isArray(msg?.references) ? msg.references : []
            return raw.map(ref => {
                    const content = ref?.reference_content
                    if (typeof content !== 'string') return null
                    try {
                        const parsed = JSON.parse(content)
                        return asCitationObject(parsed)
                    } catch (_) {
                        return null
                    }
                })
                .filter(Boolean)
        }

        // Map and add each message from the loaded conversation to the chatMessages state
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

        // Notify parent that the conversation has been loaded
        notifyParentLoaded()
        nextTick(() => {
            scrollToMessage(chatMessages.value.length - 1, false)
        })
        portalDebugLog('Loaded conversation messages successfully')
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
            errorMessage.value = _DEFAULT_ERROR_MESSAGE
            return
        }

        if (!Array.isArray(illegalContents) && typeof illegalContents === 'object' && illegalContents.success == false)
        {
            errorMessage.value = illegalContents.message || _DEFAULT_ERROR_MESSAGE
            await undoAndEditMessage(new ChatMessage('user', message, [], [], [...userFiles.value]))
            return
        }

        // Add user message to state (with all file info for display)
        const newMessage = new ChatMessage('user', message, illegalContents, [], [...userFiles.value])
        clearAllFiles() // Remove all files from UI
        chatMessages.value.push(newMessage)
        nextTick(() => {
            withProgrammaticScroll(() => scrollToBottom(false))
        })

        // Send message if no illegal content
        if (illegalContents.length === 0)
            await sendMessage(newMessage)
        else
            awaitingUserInput.value = true
    }

    const undoAndEditMessage = async (chatMessage) => {
        // Remove the transient empty assistant shell message (stream mode) if it is still last.
        const lastMessage = chatMessages.value[chatMessages.value.length - 1]
        if (lastMessage?.sender === 'assistant' && (!lastMessage.content || lastMessage.content.trim() === '')) {
            chatMessages.value.pop()
        }

        awaitingUserInput.value = false

        // Re-add user files to state
        for (let file of (chatMessage.files || [])) {
            addFile(file)
        }

        // Remove last user message
        const messageIndex = chatMessages.value.lastIndexOf(chatMessage)
        if (messageIndex >= 0) {
            chatMessages.value.splice(messageIndex, 1)
        }

        nextTick(() => {
            const input = document.querySelector('.user-input')
            if (input) input.focus()
            scrollToMessage(chatMessages.value.length - 1)
        })

        // Set user input to previous message content
        userInput.value.setUserInput(chatMessage.content)
    }

    const sendMessage = async (chatMessage) => {
        const generation = responseGeneration.value + 1
        responseGeneration.value = generation

        // Update state
        awaitingUserInput.value = false
        chatMessage.illegalContents = [] // Clear illegal contents
        awaitingResponse.value = true
        followStreamAutoScroll.value = true
        responseStatus.value = 'Assistenten tænker ...'
        completedMessageLiveText.value = ''
        startTimer()
        const isFirstMessageInConversation = chatMessages.value.length == 1

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
            const startedThreadId = await startThread()
            if (generation !== responseGeneration.value) return

            if (typeof startedThreadId === 'string' && startedThreadId.trim() !== '') {
                threadId.value = startedThreadId
                console.debug("Started new thread successfully")
            }

            if (typeof threadId.value !== 'string' || threadId.value.trim() === '') {
                console.error("Failed to start new thread.")
                stopTimer()
                awaitingResponse.value = false
                await undoAndEditMessage(chatMessage)
                errorMessage.value = _DEFAULT_ERROR_MESSAGE
                liveRegionText.value = errorMessage.value
                return
            }
        }

        if (isAgent.value) {
            const assistantMessage = new ChatMessage('assistant', '', [], [], [], 0, true)
            chatMessages.value.push(assistantMessage)

            let streamedResponse = ''
            let scrollQueued = false
            const queueStreamScroll = () => {
                if (!followStreamAutoScroll.value) return
                if (scrollQueued) return
                scrollQueued = true
                requestAnimationFrame(() => {
                    scrollQueued = false
                    if (!followStreamAutoScroll.value) return
                    withProgrammaticScroll(() => scrollToMessage(chatMessages.value.length - 1, false))
                })
            }

            const result = await sendThreadMessageStream(
                threadId.value,
                activeConversationId.value,
                message,
                chatMessage.files.map(({ name, content }) => ({ name, content })),
                useAltAssistant.value,
                currentUserEmail.value,
                {
                    onStart: (payload) => {
                        if (generation !== responseGeneration.value) return
                        if (payload?.conversation_id) {
                            activeConversationId.value = payload.conversation_id
                        }
                    },
                    onStatus: (payload) => {
                        if (generation !== responseGeneration.value) return
                        if (payload?.message) {
                            responseStatus.value = payload.message
                        }
                    },
                    onDelta: (delta) => {
                        if (generation !== responseGeneration.value) return
                        streamedResponse += delta
                        assistantMessage.content = unfilterResponseContent(streamedResponse)
                        queueStreamScroll()
                    }
                }
            )

            const { success, message: backendMessage, response, references, conversation_id, title } = result
            console.debug('Agent stream result references from backend:', references || [])

            if (generation !== responseGeneration.value)
                return  // Ignore outdated generation

            if (success === false) {
                stopTimer()
                awaitingResponse.value = false

                const assistantIndex = chatMessages.value.lastIndexOf(assistantMessage)
                 if (assistantIndex >= 0) {
                     chatMessages.value.splice(assistantIndex, 1)
                 }

                undoAndEditMessage(chatMessage)
                errorMessage.value = backendMessage || _DEFAULT_ERROR_MESSAGE
                liveRegionText.value = errorMessage.value
                return
            }

            activeConversationId.value = conversation_id

            if (isFirstMessageInConversation)
                notifyParentNewConversation({ id: conversation_id, gpt_id: ASSISTANT_NAME_ID.value, title: title || 'Ny samtale' })

            const spentTime = Number((stopTimer() / 1000).toFixed(2))
            if (!awaitingResponse.value) {
                console.warn("Response received but awaitingResponse is false. Ignoring response.")
                return
            }
            awaitingResponse.value = false

            assistantMessage.isStreaming = false
            assistantMessage.timeSpent = spentTime
            assistantMessage.references = mapApiReferences(references)

            const finalResponse = response || streamedResponse
            assistantMessage.content = unfilterResponseContent(finalResponse)
            if (!assistantMessage.content || assistantMessage.content.trim() === "") {
                assistantMessage.content = backendMessage || _DEFAULT_ERROR_MESSAGE
            }
            completedMessageLiveText.value = assistantMessage.content
            liveRegionText.value = ''

            nextTick(() => {
                if (followStreamAutoScroll.value) {
                    scrollToMessage(chatMessages.value.length - 1)
                }
                focusUserInput()
            })

            return
        }

        // Send message to backend
        const result = await sendChatMessage(activeConversationId.value, messages, currentUserEmail.value)

        // Response received from backend
        const { success, message: backendMessage, response, references, conversation_id, title } = result

        if (generation !== responseGeneration.value) {
            return
        }

        if (success === false) {
            console.error("Backend returned success=false:", backendMessage)
            stopTimer()
            awaitingResponse.value = false
            undoAndEditMessage(chatMessage)
            errorMessage.value = backendMessage || _DEFAULT_ERROR_MESSAGE
            liveRegionText.value = errorMessage.value
            return
        }

        activeConversationId.value = conversation_id

        if (isFirstMessageInConversation) // If first message - notify parent of new conversation
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
            mapApiReferences(references),
            [],
            timeSpent
        )
        if (!response || response.trim() === "") {  // No response
            // Re-add user files to state
            for (let file of chatMessage.files) {
                addFile(file)
            }
            assistantMessage.content = backendMessage || _DEFAULT_ERROR_MESSAGE
        }
        chatMessages.value.push(assistantMessage)
        completedMessageLiveText.value = assistantMessage.content
        liveRegionText.value = ''

        // Update UI
        nextTick(() => {
            scrollToMessage(chatMessages.value.length - 1)
            focusUserInput()
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
        adjustChatMessagesPaddingBottom()
        adjustAltTogglePosition()
    }
    function onClearFiles() {
        userFiles.value = []
        adjustChatMessagesPaddingBottom()
        adjustAltTogglePosition()
    }
    function clearAllFiles() {
        let removedFiles = [...userFiles.value]
        userFiles.value = []
        adjustChatMessagesPaddingBottom()
        adjustAltTogglePosition()
        return removedFiles
    }
    function addFile(fileObj) {
        userFiles.value.push(fileObj)
        adjustChatMessagesPaddingBottom()
        adjustAltTogglePosition()
    }

    // Scroll to specific message
    function scrollToBottom(smoothScroll = true) {
        window.scrollTo({
            left: 0,
            top: document.documentElement.scrollHeight,
            behavior: smoothScroll ? 'smooth' : 'auto'
        })
    }

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

    function focusUserInput() {
        const input = document.querySelector('.user-input')
        if (!input) return
        if (document.activeElement === input) return
        if (typeof input.focus === 'function') {
            input.focus({ preventScroll: true })
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
        :sticky="!errorMessage"
    />
    <Alert
        v-if="errorMessage"
        type="error"
        :message="errorMessage"
        :sticky="true"
    />

    <div style="margin-bottom: auto"></div><!-- spacer to force alerts to top and chat to bottom -->

    <div class="welcome-header" v-if="chatMessages.length == 0">
        Hej, hvad kan jeg hjælpe med?
        <div class="assistant-description" style="white-space: pre-line;">{{ assistantDescription }}</div>
    </div>

    <div id="chat-messages" ref="chatMessagesEl">
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
                :isStreaming="msg.isStreaming"
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
            <span>{{ responseStatus }}</span>
            <span class="timer">
                <i class="fa-regular fa-clock"></i>
                {{ (timeSpent / 1000).toFixed(2) }}
            </span>
        </div>
    </div>

    <div class="sr-only-live" aria-live="polite" :aria-atomic="false" aria-relevant="additions text">{{ liveRegionText }}</div>
    <div class="sr-only-live" aria-live="polite" :aria-atomic="true" aria-relevant="additions text">{{ completedMessageLiveText }}</div>

    <div :class="['user-input-container', { 'landing-page': chatMessages.length == 0 }]" ref="userInputContainer">
        <UserInput
            ref="userInput"
            @send="onUserInput"
            @toggle-alt-assistant="val => useAltAssistant = val"
            :showAssistantToggle="showAssistantToggle && (chatMessages.length == 0 || chatMessages[chatMessages.length - 1].illegalContents.length == 0)"
            :disabled="awaitingResponse || awaitingUserInput"
            :fixed="chatMessages.length > 0"
        />

        <div ref="fileUploadRootEl">
            <FileUpload
                ref="fileUploader"
                :files="userFiles"
                :assistantType="assistantType"
                :maxFileSizeBytes="agentFileSizeLimit"
                :showAssistantTogglePadding="showAssistantToggle && chatMessages.length != 0"
                @add-file="addFile"
                @remove-file="onFileRemoved"
                @clear-files="onClearFiles" />
        </div>
    </div>
</template>

<style scoped>
    .welcome-header {
        font-size: 1.6rem;
        text-align: center;
        width: max-content;
        z-index: 3;
        pointer-events: none;
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
    .rotate {
        animation: l24 1.5s infinite linear;
    }
    @keyframes l24 {
        100% {transform: rotate(1turn)}
    }

    .sr-only-live {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
    }

    #chat-messages {
        padding-bottom: 1.5rem;
        padding-top: 0.5rem;
    }

    .user-input-container {
        z-index: 10;
        position: relative;
        position: sticky;
        bottom: 0rem;
        padding-bottom: 2rem;
        width: 100%;
        background-color: var(--color-background-primary);
    }
    @media screen and (min-width: 875px) {
        .user-input-container  {
            max-width: 56rem;
        }
    }
    .user-input-container.landing-page {
        margin-bottom: auto;
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
        flex-direction: column-reverse;
        gap: 0.3rem;
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
    @media screen and (min-width: 560px) {
        .alert--buttons {
            flex-direction: row;
            gap: 0;
        }
    }
</style>
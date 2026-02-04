<script setup>
    import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
    import Header from './components/Header.vue'
    import Chat from './views/Chat.vue'
    import { isAllowedPortalMessageEvent, normalizePortalMessage, notifyParentReady, portalDebugLog } from './utils/portalMessaging.js'

    const chat = ref(null)
    const userEmail = ref(null)

    const hasChatMessages = computed(() => {
        return chat.value && chat.value.chatMessages && chat.value.chatMessages.length > 0
    })

    function clearChat() {
        // Trigger fade-out and fade-in animation
        document.querySelector('#app').classList.remove('fade-in')
        document.querySelector('#app').classList.add('fade-out')
        setTimeout(() => {
            chat.value.clearChat()
            document.querySelector('#app').classList.remove('fade-out')
            document.querySelector('#app').classList.add('fade-in')
            const input = document.querySelector('.user-input')
            if (input) input.focus()
        }, 500)
        setTimeout(() => {
            document.querySelector('#app').classList.remove('fade-in')
        }, 1100)
    }

    onMounted(() => {
        portalDebugLog('Mounted. origin=', window.location.origin, 'href=', window.location.href)

        const input = document.querySelector('.user-input')
        if (input)
            input.focus()

        notifyParentReady()
        portalDebugLog('Attaching window message listener')
        window.addEventListener('message', onPortalMessage)
    })

    onBeforeUnmount(() => {
        window.removeEventListener('message', onPortalMessage)
    })

    // Handle messages from parent portal
    function onPortalMessage(event) {
        if (!isAllowedPortalMessageEvent(event)) return

        const msg = normalizePortalMessage(event.data)
        if (!msg) return

        portalDebugLog('Portal message received:', msg)

        switch (msg.type) {
            case 'PARENT_INIT': {
                // Parent portal has acknowledged the READY message
                // Response contains user email
                userEmail.value = msg.userEmail || null
                portalDebugLog('Parent portal acknowledged READY message. User email set:', userEmail.value)
                return
            }
            case 'LOAD_CONVERSATION': {
                const conversationId = msg.id
                const portalUserEmail = msg.userEmail ?? userEmail.value

                if (!conversationId) return
                if (chat.value?.loadConversation) {
                    chat.value.loadConversation(conversationId, portalUserEmail)
                } else {
                    console.error('Chat component does not expose loadConversation.')
                }
                return
            }
            case 'CLEAR_CONVERSATION': {
                if (chat.value?.clearChat) chat.value.clearChat()
                return
            }
            default:
                return
        }
    }
</script>

<template>
    <Header @clear-chat="clearChat" :show-start-new-chat="hasChatMessages" />
    <Chat ref="chat" :user-email="userEmail" />
</template>

<style scoped>

</style>
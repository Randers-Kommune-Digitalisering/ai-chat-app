<script setup>
    import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
    import Header from './components/Header.vue'
    import Chat from './views/Chat.vue'
    import { isAllowedPortalOrigin, normalizePortalMessage, notifyParentReady, portalDebugLog } from './utils/portalMessaging.js'

    const chat = ref(null)

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

    function onPortalMessage(event) {
        // Log BEFORE filtering so we can distinguish “not received” vs “filtered out”.
        portalDebugLog('Raw message event:', { origin: event.origin, data: event.data })

        if (!isAllowedPortalOrigin(event.origin)) return

        const msg = normalizePortalMessage(event.data)
        if (!msg) return

        switch (msg.type) {
            case 'LOAD_CONVERSATION': {
                const conversationId = msg.conversationId
                if (!conversationId) return
                if (chat.value?.loadConversation) {
                    chat.value.loadConversation(conversationId)
                } else {
                    console.warn('Chat component does not expose loadConversation yet.')
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
    <Chat ref="chat" />
</template>

<style scoped>

</style>
<script setup>
    import { ref, onMounted, computed } from 'vue'
    import Header from './components/Header.vue'
    import Chat from './views/Chat.vue'

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
        const input = document.querySelector('.user-input')
        if (input) input.focus()
    })
</script>

<template>
    <Header @clear-chat="clearChat" :show-start-new-chat="hasChatMessages" />
    <Chat ref="chat" />
</template>

<style scoped>

</style>
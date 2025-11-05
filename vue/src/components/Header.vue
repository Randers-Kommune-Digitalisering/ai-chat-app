<script setup>
import { ref, getCurrentInstance } from 'vue'
const ASSISTANT_NAME = getCurrentInstance().appContext.config.globalProperties.$config.assistantName || 'AI Assistent'

const props = defineProps({
    showStartNewChat: {
        type: Boolean,
        default: true
    }
})

const rotating = ref(false)
const recentlyActivated = ref(false)
const emit = defineEmits(['clear-chat'])

function triggerRotate() {
    if (rotating.value) return
    rotating.value = true

    setTimeout(() => {
        recentlyActivated.value = true
        setTimeout(() => {
            recentlyActivated.value = false
        }, 1500) // duration to show checkmark
    }, 700) // just before rotation ends

    setTimeout(() => {
        rotating.value = false
    }, 800) // rotation ends
}

function clearChat() {
    // Emit event to parent to clear chat
    emit('clear-chat')
}
</script>
<template>
    <div class="header">
        <div class="header-title">{{ ASSISTANT_NAME }}</div>
        <div
            :class="['header-action', { 'hidden': !showStartNewChat }]"
            @click="clearChat(); triggerRotate()"
        >
            <div class="header-action-icon">
                <i
                    :class="['', (recentlyActivated ? 'fa-regular fa-circle-check' : 'fa-solid fa-arrow-rotate-left'), { 'rotate': rotating }]"
                ></i>
            </div>
            <div class="header-action-text">Start ny samtale</div>
        </div>
    </div>
</template>
<style scoped>
    .header {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
        height: 3.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.5rem;
        background-color: var(--color-toolbar-background);
        border-bottom: 0.05rem solid var(--color-toolbar-border);
        color: var(--color-text-faded);
        text-align: center;
        z-index: 12;
    }
    .header > div.header-title {
        font-size: 1.1rem;
        font-weight: 500;
        color: var(--color-text-primary)
    }
    .header > div.header-action {
        opacity: 1;
        user-select: none;
        cursor: pointer;
        transition: color 0.2s ease, opacity 0.3s ease 0.8s;
        font-size: 0.9rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    .header > div.header-action.hidden {
        opacity: 0;
        pointer-events: none;
    }
    .header > div.header-action:hover {
        color: var(--color-text-primary);
    }
    .header-action-icon {
        display: flex;
        justify-content: center;
        align-items: center;
        transform: translateY(0.02rem);
    }
    .header > div.header-action i {
        font-size: 0.9em;
        transition: transform 0.3s ease;
    }
    .header > div.header-action:hover i:not(.rotate) {
        animation: shake-rotate 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .rotate {
        animation: shake-rotate 1.5s linear;
    }
    @keyframes shake-rotate {
        0% {
        transform: rotate(0deg);
        }
        20% {
        transform: rotate(20deg);
        }
        40% {
        transform: rotate(-20deg);
        }
        60% {
        transform: rotate(15deg);
        }
        80% {
        transform: rotate(-10deg);
        }
        100% {
        transform: rotate(0deg);
        }
    }
    .rotate {
        animation: l24 0.8s linear;
    }
    @keyframes l24 {
        0% {
        transform: rotate(0deg);
        }
        15% {
        transform: rotate(40deg);
        }
        60% {
        transform: rotate(-340deg);
        }
        80% {
        transform: rotate(-370deg);
        }
        100% {
        transform: rotate(-360deg);
        }
    }
</style>
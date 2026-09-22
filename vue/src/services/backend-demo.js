export async function startThread() {
    await new Promise(resolve => setTimeout(resolve, Math.random() * 500 + 100)); // Wait for 100-600 ms
    return {
        threadId: "demo-thread-123"
    }
}

export async function sendThreadMessage(threadId, conversationId, message, files, useAlt = false, userEmail = null) {
    await new Promise(resolve => setTimeout(resolve, Math.random() * 2000 + 1000)); // Wait for 1-3 seconds
    return {
        response: "This is a demo response to your message: " + message,
        references: [
            { title: "Eksempel Reference", url: "https://example.com" }
        ],
        conversation_id: conversationId || 1,
        user_email: userEmail
    }
}

export async function sendChatMessage(conversationId, messages, userEmail = null) {
    console.info("Sending demo chat message with messages:", messages);
    await new Promise(resolve => setTimeout(resolve, Math.random() * 2000 + 1000)); // Wait for 1-3 seconds
    return {
        response: "This is a demo chat response based on your messages.",
        references: [
            { title: "Demo Chat Reference", url: "https://example.com/chat" }
        ],
        conversation_id: conversationId || 1,
        user_email: userEmail
    }
}

export async function sendFeedback(feedback, responseIndex, chatHistory) {
    await new Promise(resolve => setTimeout(resolve, Math.random() * 500 + 100)); // Simulate network delay
    return {
        success: true,
        data: {
            feedback,
            responseIndex,
            chatHistory
        }
    };
}

export function getIllegalContents(message) {
    // Simple demo filter that returns list of filtered words
    const filteredWords = ["test"];
    const foundWords = filteredWords.filter(word => message.toLowerCase().includes(word));
    return foundWords;
}

export async function fetchConversationByPermit(permit) {
    await new Promise(resolve => setTimeout(resolve, Math.random() * 500 + 100)); // Simulate network delay

    if (!permit || typeof permit !== 'string' || !permit.trim()) {
        return { success: false, message: 'Kunne ikke indlæse samtalen. Prøv igen senere.' }
    }

    const now = Date.now()

    // Mirror the real backend response from POST /api/conversations/load
    // (see flask/src/api_endpoints.py -> load_conversation_by_permit).
    return {
        success: true,
        conversation: {
            id: 123,
            is_active: true,
            title: 'Demo samtale',
            gpt_id: 'demo-assistant',
            user_email: 'demo.user@example.com',
            created_at: new Date(now - 1000 * 60 * 60).toISOString(),
            updated_at: new Date(now).toISOString(),
            thread_id: 'demo-thread-123',
            messages: [
                {
                    id: 1,
                    conversation_id: 123,
                    sender: 'user',
                    content: 'Hello, this is a demo conversation.',
                    timestamp: new Date(now - 1000 * 60 * 55).toISOString(),
                    attachments: [
                        {
                            id: 1,
                            message_id: 1,
                            file_name: 'demo.txt',
                            file_type: 'text/plain',
                            file_size: 11,
                            // "Hello world" base64; UI uses this to continue chat with same context.
                            file_content: 'SGVsbG8gd29ybGQ='
                        }
                    ],
                    references: []
                },
                {
                    id: 2,
                    conversation_id: 123,
                    sender: 'assistant',
                    content: 'Hi! How can I assist you today?',
                    timestamp: new Date(now - 1000 * 60 * 54).toISOString(),
                    attachments: [],
                    references: [
                        {
                            id: 1,
                            message_id: 2,
                            reference_type: 'url',
                            // Stored as JSON string in DB-backed backend.
                            reference_content: JSON.stringify({ title: 'Demo Chat Reference', url: 'https://example.com/chat' })
                        }
                    ]
                }
            ]
        }
    };
}
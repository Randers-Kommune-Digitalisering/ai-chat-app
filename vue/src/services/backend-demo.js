export async function startThread() {
    await new Promise(resolve => setTimeout(resolve, Math.random() * 500 + 100)); // Wait for 100-600 ms
    return {
        threadId: "demo-thread-123"
    }
}

export async function sendThreadMessage(threadId, message, files) {
    await new Promise(resolve => setTimeout(resolve, Math.random() * 2000 + 1000)); // Wait for 1-3 seconds
    return {
        response: "This is a demo response to your message: " + message,
        references: [
            { title: "Eksempel Reference", url: "https://example.com" }
        ]
    }
}

export async function sendChatMessage(messages) {
    console.log("Sending chat message with messages:", messages);
    await new Promise(resolve => setTimeout(resolve, Math.random() * 2000 + 1000)); // Wait for 1-3 seconds
    return {
        response: "This is a demo chat response based on your messages.",
        references: [
            { title: "Demo Chat Reference", url: "https://example.com/chat" }
        ]
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

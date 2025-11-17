import axios from 'axios';

export async function startThread() {
    try {
        const result = await axios.post('/api/threads');
        if (!result.data.thread_id) {
            throw new Error("No thread_id returned from backend");
        }
        return result.data.thread_id;
    } catch (error) {
        console.error("Error starting thread:", error);
        throw error;
    }
}

export async function sendThreadMessage(threadId, message, files) {
    try {
        const result = await axios.post(`/api/threads/${threadId}/messages`, { message, files });
        return {
            response: result.data.response,
            references: result.data.references
        }
    } catch (error) {
        console.error("Error sending message:", error);
        throw error;
    }
}

export async function sendChatMessage(messages) {
    try {
        const result = await axios.post('/api/chat/messages', { messages });
        return {
            response: result.data.response,
            references: result.data.references
        }
    } catch (error) {
        console.error("Error sending chat message:", error);
        throw error;
    }
}

export async function sendFeedback(feedback, responseIndex, chatHistory) {
    try {
        const result = await axios.post('/api/feedback', {
            feedback,
            response_index: responseIndex,
            chat_history: chatHistory
        });
        return result.data;
    } catch (error) {
        console.error("Error sending feedback:", error);
        throw error;
    }
}

export async function getIllegalContents(message) {
    try {
        const result = await axios.post('/api/filter', { content: message });
        return result.data.filtered_content || [];
    } catch (error) {
        console.error("Error filtering message:", error);
        throw error;
    }
}

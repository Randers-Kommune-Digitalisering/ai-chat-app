import axios from 'axios';


    async function _createConversation(initialMessage, userEmail, threadId = null) {
    try {
        const result = await axios.post('/api/conversations', {
            initial_message: initialMessage,
            user_email: userEmail,
            thread_id: threadId
        });
        return result.data.conversation_id;
    } catch (error) {
        console.error("Error creating conversation:", error);
        throw error;
    }
}

export async function fetchConversation(conversationId, userEmail) {
    try {
        const response = await axios.get(`/api/conversations/${conversationId}`, {
            headers: { 'X-User-Email': userEmail }
        });
        console.log("Fetched conversation data:", response.data);
        return response.data;
    } catch (error) {
        console.error("Error getting conversation messages:", error);
        throw error;
    }
}

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

export async function sendThreadMessage(threadId, conversationId, message, files, useAlt = false) {
    try {
        const result = await axios.post(`/api/threads/${threadId}/messages`, { message, files, use_alt: useAlt });
        return {
            response: result.data.response,
            references: result.data.references
        }
    } catch (error) {
        console.error("Error sending message:", error);
        throw error;
    }
}

export async function sendChatMessage(conversationId, messages) {
    try {
        const result = await axios.post('/api/chat/messages', { messages, conversation_id: conversationId });
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

export async function sendLikeFeedback(responseIndex) {
    try {
        const result = await axios.post('/api/feedback/like', {
            response_index: responseIndex
        });
        return result.data;
    } catch (error) {
        console.error("Error sending like feedback:", error);
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

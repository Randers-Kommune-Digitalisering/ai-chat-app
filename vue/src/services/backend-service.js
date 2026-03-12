import axios from 'axios';


export async function fetchConversationByPermit(permit) {
    try {
        if (!permit || typeof permit !== 'string') {
            throw new Error('permit is required');
        }

        const response = await axios.post(
            '/api/conversations/load',
            {},
            { headers: { Authorization: `Bearer ${permit}` } }
        );
        return response.data;
    } catch (error) {
        console.error('Error loading conversation by permit:', error);
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

export async function sendThreadMessage(threadId, conversationId, message, files, useAlt = false, userEmail = null) {
    try {
        const result = await axios.post(
            `/api/threads/${threadId}/messages`,
            { message, files, use_alt: useAlt, conversation_id: conversationId },
            { headers: userEmail ? { 'X-User-Email': userEmail } : undefined }
        );
        return {
            success: result.data.success,
            message: result.data.message,
            response: result.data.response,
            references: result.data.references,
            conversation_id: result.data.conversation_id,
            title: result.data.title
        }
    } catch (error) {
        console.error("Error sending message:", error);
        throw error;
    }
}

export async function sendChatMessage(conversationId, messages, userEmail = null) {
    try {
        const result = await axios.post(
            '/api/chat/messages',
            { messages, conversation_id: conversationId },
            { headers: userEmail ? { 'X-User-Email': userEmail } : undefined }
        );
        return {
            success: result.data.success,
            message: result.data.message,
            response: result.data.response,
            references: result.data.references,
            conversation_id: result.data.conversation_id,
            title: result.data.title
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

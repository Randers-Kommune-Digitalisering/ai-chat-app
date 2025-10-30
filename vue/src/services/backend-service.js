import axios from 'axios';

export async function startThread() {
    try {
        const response = await axios.post('/api/threads');
        return response.data;
    } catch (error) {
        console.error("Error starting thread:", error);
        throw error;
    }
}

export async function sendMessage(threadId, message, files) {
    try {
        const response = await axios.post('/api/messages', { threadId, message, files });
        return response.data;
    } catch (error) {
        console.error("Error sending message:", error);
        throw error;
    }
}
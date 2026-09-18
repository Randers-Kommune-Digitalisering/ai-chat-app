import axios from 'axios';


export async function fetchConversationByPermit(permit) {
    try {
        if (!permit || typeof permit !== 'string') {
            throw new Error('permit is required');
        }

        const trimmedPermit = permit.trim();
        if (!trimmedPermit) {
            throw new Error('permit is required');
        }

        const response = await axios.post(
            '/api/conversations/load',
            {},
            { headers: { Authorization: `Bearer ${trimmedPermit}` } }
        );
        return response.data;
    } catch (error) {
        console.error('Error loading conversation by permit:', error?.response?.data || error);
        return error?.response?.data || { 'success': false, 'message': 'Kunne ikke indlæse samtalen. Prøv igen senere.' };
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
        console.error("Error starting thread:", error?.response?.data || error);
        return error?.response?.data || { 'success': false, 'message': 'Der opstod en fejl. Prøv at genindlæse siden.' };
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
        console.error("Error sending message:", error?.response?.data || error);
        return error?.response?.data || { 'success': false, 'message': 'Der opstod en fejl. Prøv at genindlæse siden.' };
    }
}

export async function sendThreadMessageStream(threadId, conversationId, message, files, useAlt = false, userEmail = null, handlers = {}) {
    const { onStart, onStatus, onDelta, onEnd, onError } = handlers;

    try {
        const headers = { 'Content-Type': 'application/json' };
        if (userEmail) {
            headers['X-User-Email'] = userEmail;
        }

        const response = await fetch(`/api/threads/${threadId}/messages/stream`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
                message,
                files,
                use_alt: useAlt,
                conversation_id: conversationId,
            }),
        });

        if (!response.ok) {
            let errorPayload = null;
            try {
                errorPayload = await response.json();
            } catch (_) {
                errorPayload = null;
            }

            const backendMessage = errorPayload?.message || 'Der opstod en fejl. Prøv at genindlæse siden.';
            if (typeof onError === 'function') {
                onError({ message: backendMessage, status: response.status });
            }
            return {
                success: false,
                message: backendMessage,
                status: response.status,
            };
        }

        if (!response.body) {
            const fallback = { success: false, message: 'Streaming er ikke tilgængelig i denne browser.' };
            if (typeof onError === 'function') {
                onError({ message: fallback.message, status: 500 });
            }
            return fallback;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let finalPayload = null;
        let errorPayload = null;

        const processEventBlock = (block) => {
            if (!block) return;

            let eventName = 'message';
            const dataLines = [];

            for (const line of block.split(/\r?\n/)) {
                if (!line) continue;
                if (line.startsWith(':')) continue;
                if (line.startsWith('event:')) {
                    eventName = line.slice(6).trim();
                    continue;
                }
                if (line.startsWith('data:')) {
                    dataLines.push(line.slice(5).trim());
                }
            }

            const dataText = dataLines.join('\n');
            let payload = {};
            if (dataText) {
                try {
                    payload = JSON.parse(dataText);
                } catch (_) {
                    payload = { message: dataText };
                }
            }

            if (eventName === 'start') {
                if (typeof onStart === 'function') onStart(payload);
                return;
            }
            if (eventName === 'status') {
                if (typeof onStatus === 'function') onStatus(payload);
                return;
            }
            if (eventName === 'delta') {
                const deltaText = payload?.text || '';
                if (deltaText && typeof onDelta === 'function') onDelta(deltaText);
                return;
            }
            if (eventName === 'end') {
                finalPayload = payload;
                console.info('SSE end event references received:', payload?.references || []);
                if (typeof onEnd === 'function') onEnd(payload);
                return;
            }
            if (eventName === 'error') {
                errorPayload = payload;
                if (typeof onError === 'function') onError(payload);
            }
        };

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            let separatorIndex = buffer.indexOf('\n\n');
            while (separatorIndex !== -1) {
                const block = buffer.slice(0, separatorIndex);
                buffer = buffer.slice(separatorIndex + 2);
                processEventBlock(block);
                separatorIndex = buffer.indexOf('\n\n');
            }
        }

        buffer += decoder.decode();
        if (buffer.trim()) {
            processEventBlock(buffer.trim());
        }

        if (finalPayload) {
            console.info('Stream final payload references returned to view:', finalPayload?.references || []);
            return {
                success: finalPayload.success !== false,
                message: finalPayload.message,
                response: finalPayload.response,
                references: finalPayload.references,
                conversation_id: finalPayload.conversation_id,
                title: finalPayload.title,
            };
        }

        if (errorPayload) {
            return {
                success: false,
                message: errorPayload.message || 'Assistenten havde en midlertidig fejl. Genindlæs siden eller prøv igen senere.',
            };
        }

        return { success: false, message: 'Stream blev afbrudt før svar var færdigt.' };
    } catch (error) {
        console.error('Error streaming message:', error);
        const message = 'Der opstod en fejl. Prøv at genindlæse siden.';
        if (typeof onError === 'function') {
            onError({ message, status: 500 });
        }
        return { success: false, message };
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
        console.error("Error sending chat message:", error?.response?.data || error);
        return error?.response?.data || { 'success': false, 'message': 'Der opstod en fejl med forbindelsen til serveren. Genindlæs siden eller prøv igen senere.' };
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
        console.error("Error sending feedback:", error?.response?.data || error);
        return error?.response?.data || { 'success': false, 'message': 'Der opstod en fejl, og din feedback blev ikke sendt. Genindlæs siden eller prøv igen senere.' };
    }
}

export async function sendLikeFeedback(responseIndex) {
    try {
        const result = await axios.post('/api/feedback/like', {
            response_index: responseIndex
        });
        return result.data;
    } catch (error) {
        console.error("Error sending like feedback:", error?.response?.data || error);
        return error?.response?.data || { 'success': false, 'message': 'Der opstod en fejl, og din feedback blev ikke registreret. Genindlæs siden eller prøv igen senere.' };
    }
}

export async function getIllegalContents(message) {
    try {
        const result = await axios.post('/api/filter', { content: message });
        return result.data.filtered_content || [];
    } catch (error) {
        console.error("Error filtering message:", error?.response?.data || error);
        return error?.response?.data || { 'success': false, 'message': 'Der opstod en fejl med forbindelsen til serveren. Genindlæs siden eller prøv igen senere.' };
    }
}

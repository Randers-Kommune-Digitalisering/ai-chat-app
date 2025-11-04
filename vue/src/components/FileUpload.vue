<script setup>

    import { ref, onMounted, onUnmounted } from 'vue'

    const fileTypesAccepted = [
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // .docx
        'application/msword', // .doc + .dot
        'text/markdown', // .md
        'text/x-markdown', // .md (alternative MIME type)
        'text/plain' // .txt + .text
    ]
    const emit = defineEmits(['remove-file', 'file-upload-adjust-css', 'add-file', 'clear-files'])

    const props = defineProps({
        files: {
            type: Array,
            required: true
        }
    })
    const isDragging = ref(false)
    const isOverDropZone = ref(false)
    const filesAwaitingUpload = ref(0)
    const filesTotalToUpload = ref(0)
    const fileDropped = ref(false)
    const fileUploaded = ref(false)
    const fileInputRef = ref(null)
    const fileNotAccepted = ref(false)

    function onDrop(e) {
        e.preventDefault()
        isDragging.value = false
        isOverDropZone.value = false
        const files = [...e.dataTransfer.files]

        uploadFiles(files)
    }

    async function readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                // Remove the data:*/*;base64, prefix if present
                const base64 = reader.result.split(',')[1];
                resolve(base64);
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    async function uploadFiles(files, simulateDrop = true) {
        const acceptedFiles = files.filter(file => fileTypesAccepted.includes(file.type))
        filesAwaitingUpload.value = filesTotalToUpload.value = acceptedFiles.length
        fileDropped.value = true
        if (acceptedFiles.length > 0) {

            // Read all files as base64
            const filesWithContent = await Promise.all(
                acceptedFiles.map(async file => ({
                    name: file.name,
                    size: file.size,
                    type: file.type,
                    content: await readFileAsBase64(file),
                    hover: false
                }))
            )

            // Initiate upload animation in input field
            const totalUploadTime = 300 + (filesWithContent.length - 1) * 500
            const showFileDropTime = totalUploadTime + 1000
            setTimeout(() => {
                fileDropped.value = false
            }, showFileDropTime)

            // Simulate staggered uploads
            for (let i = 0; i < filesWithContent.length; i++) {
                setTimeout(() => {
                    // Emit to parent to add files
                    addFile(filesWithContent[i])
                    filesAwaitingUpload.value--
                }, 300 + i * 500)
            }

            // When all files are uploaded, show success notification
            setTimeout(() => {
                fileUploaded.value = true
            }, totalUploadTime)
            // Hide success notification after 2 seconds
            setTimeout(() => {
                fileUploaded.value = false
                filesTotalToUpload.value = 0
            }, totalUploadTime + 2000)

        } else {
            console.log("File type not accepted")
            // Show error notification for 2 seconds
            fileNotAccepted.value = true
            setTimeout(() => {
                fileDropped.value = false
            }, 2000)
            setTimeout(() => {
                fileNotAccepted.value = false
            }, 2500)
        }
    }

    function removeFile(file) {
        emit('remove-file', file)
    }
    function addFile(fileObj) {
        emit('add-file', fileObj)
    }

    function onDropZoneDragEnter(e) {
        e.preventDefault()
        isOverDropZone.value = true
    }
    function onDropZoneDragLeave(e) {
        e.preventDefault()
        isOverDropZone.value = false
    }

    let dragCounter = 0
    function handleWindowDragEnter(e) {
        dragCounter++
        isDragging.value = true
    }
    function handleWindowDragLeave(e) {
        dragCounter--
        if (dragCounter <= 0) {
            isDragging.value = false
            dragCounter = 0
        }
    }

    function handleWindowDrop(e) {
        // If user is dragging files and not over dropZone, prevent default (avoid browser opening file)
        if (isDragging.value && !isOverDropZone.value) {
            e.preventDefault()
        }
        isDragging.value = false
        isOverDropZone.value = false
        dragCounter = 0
    }
    function handleOverlayDragOver(e) {
        e.preventDefault()
    }
    function preventWindowDragOver(e) {
        // Only prevent if dragging files
        if (e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files')) {
            e.preventDefault()
        }
    }
    function preventWindowDrop(e) {
        // Only prevent if dragging files and not over dropZone
        if (e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files')) {
            e.preventDefault()
        }
    }

    onMounted(() => {
        window.addEventListener('dragenter', handleWindowDragEnter)
        window.addEventListener('dragleave', handleWindowDragLeave)
        window.addEventListener('drop', handleWindowDrop)
        window.addEventListener('dragover', preventWindowDragOver)
        document.body.addEventListener('drop', preventWindowDrop)
    })
    onUnmounted(() => {
        window.removeEventListener('dragenter', handleWindowDragEnter)
        window.removeEventListener('dragleave', handleWindowDragLeave)
        window.removeEventListener('drop', handleWindowDrop)
        window.removeEventListener('dragover', preventWindowDragOver)
        document.body.removeEventListener('drop', preventWindowDrop)
    })
</script>

<template>
    <div class="fileUploads" id="file-uploads">
        <div
            v-for="(file, index) in files"
            :key="index"
            class="file-upload-item"
            @click="removeFile(file)"
            @mouseenter="file.hover = true"
            @mouseleave="file.hover = false"
        >
            <i v-if="!file.hover" class="fa-regular fa-file"></i>
            <i v-else class="fa-solid fa-trash"></i>
            {{ file.name }} ({{ (file.size / 1024).toFixed(0) }} KB)
        </div>
    </div>

    <button
        type="button"
        :class="['fileSelectButton', { 'disabled': isDragging || fileDropped }]"
        :disabled="isDragging || fileDropped"
        @click="() => fileInputRef.click()"
    >
        <i class="fa-solid fa-plus"></i>
        <div class="tooltip">
            Upload dokument
            <i class="fa-regular fa-file"></i>
        </div>
    </button>

    <input
        ref="fileInputRef"
        type="file"
        multiple
        style="display: none;"
        @change="e => {
            const files = [...e.target.files]
            uploadFiles(files, true)
            e.target.value = ''
        }"
        :accept="fileTypesAccepted.join(', ')"
    />

    <div
        @drop.prevent="onDrop"
        @dragover="handleOverlayDragOver"
        @dragenter="onDropZoneDragEnter"
        @dragleave="onDropZoneDragLeave"
        :class="['dropZone', { 'dragging': isDragging, 'dropped': fileDropped, 'error': fileNotAccepted }]"
        :style="{ pointerEvents: isDragging ? 'auto' : 'none' }"
    ></div>

    <div
        class="dropOverlay"
        @dragover="handleOverlayDragOver"
        @drop.prevent="onDrop"
        :style="{ pointerEvents: isDragging ? 'auto' : 'none' }"
    >
        <div :class="{ 'over-zone': isOverDropZone }">

            <template v-if="isOverDropZone">
                Slip filen her ...
            </template>

            <template v-else>

                <template v-if="fileDropped && !fileUploaded && !fileNotAccepted">
                    <i class="fa-solid fa-rotate rotate"></i>
                    <span>
                        Uploader {{ 
                            filesTotalToUpload > 1 ?
                                ((filesTotalToUpload - filesAwaitingUpload + 1) + " / " + filesTotalToUpload)
                                : "filen"
                        }}
                    </span>
                </template>

                <template v-if="fileNotAccepted">
                    <i class="fa-solid fa-circle-exclamation"></i>
                    <span>Ugyldig filtype</span>
                </template>

                <template v-if="fileUploaded">
                    <i class="fa-solid fa-check"></i>
                    <span>{{ filesTotalToUpload > 1 ? 'Filerne' : 'Filen' }} er uploadet</span>
                </template>

                <template v-if="!fileUploaded && !fileDropped && !fileNotAccepted">
                    <span>Træk og slip filen her for at uploade</span>
                </template>

            </template>

        </div>
    </div>
</template>

<style scoped>
    .fileSelectButton {
        position: absolute;
        top: 1rem;
        bottom: 2rem;
        left: 0.8rem;
        right: 0.8rem;
        width: 2.5rem;
        padding-left: 1rem;
        z-index: 20;
        cursor: pointer;
        background-color: transparent;
        border: 0;
        color: var(--color-input-fileselect-button);
        transition: opacity 0.3s, color 0.2s ease;
    }
    .fileSelectButton:hover {
        color: var(--color-input-fileselect-button-hover);
    }
    .fileSelectButton > i {
        transform: translateY(0.05rem)
    }
    .fileSelectButton:disabled {
        opacity: 0;
    }
    .fileSelectButton .tooltip {
        bottom: 50%;
        left: 2.5rem;
        background-color: var(--color-input-background);
        font-size: 1em;
        pointer-events: none;
        transform: translateY(50%);
        padding: 0.5rem 0.8rem;
        color: inherit;
    }
    .fileSelectButton .tooltip i {
        margin-left: 0.4rem;
        font-size: 0.8em;
    }

    .dropZone {
        position: absolute;
        top: 0rem;
        bottom: 1rem;
        left: 0.8rem;
        right: 0.8rem;
        z-index: 10;
    }
    .dropOverlay {
        position: absolute;
        top: 1rem;
        bottom: 2rem;
        left: 0.8rem;
        right: 0.8rem;
        opacity: 0;
        border-radius: 2rem;
        transition: opacity 0.3s;
    }
        .dropOverlay > div {
            height: 100%;
            display: flex;
            justify-content: center;
            align-items: center;
            flex-direction: column;
            gap: 1rem;
            border-radius: 2rem;
            border: 0.05rem solid var(--color-input-border);
            color: var(--color-text-primary);
            background-color: var(--color-input-background);
        }

        .dropZone.dragging ~ .dropOverlay, .dropZone.dropped ~ .dropOverlay {
            opacity: 1;
        }
        .dropOverlay > div {
            display: flex;
            justify-content: center;
            align-items: center;
            flex-direction: row;
            transition: border 0.2s ease, color 0.2s ease, background-color 0.2s ease-in-out;
        }
        .dropZone.dragging ~ .dropOverlay > div {
            border: 0.2rem dashed var(--color-input-border);
            color: var(--color-dropzone-text);
            transition: border 0.2s ease, color 0.2s ease, background-color 0.2s ease-in-out;
        }
        .dropZone.dropped:not(.error) ~ .dropOverlay > div {
            border: 0.2rem dashed var(--color-dropzone-green-border) !important;
            color: var(--color-dropzone-green) !important;
            background-color: var(--color-dropzone-background-active);
        }
        .dropZone.error ~ .dropOverlay > div {
            border: 0.2rem dashed var(--color-dropzone-red-border) !important;
            color: var(--color-dropzone-red) !important;
            background-color: var(--color-dropzone-background-active);
        }
        .dropZone.dragging ~ .dropOverlay > div.over-zone{
            border: 0.2rem dashed var(--color-dropzone-yellow-border) !important;
            color: var(--color-dropzone-yellow) !important;
            background-color: var(--color-dropzone-background-active);
        }

        .rotate {
            animation: l24 1.5s infinite linear;
        }
        @keyframes l24 {
            100% {transform: rotate(1turn)}
        }

    .fileUploads {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        transform: translateY(-100%);
        padding-left: 1rem;
        background-color: var(--color-background-primary);
        padding-top: 0.5rem;

        display: flex;
        flex-direction: row;
        flex-wrap: wrap-reverse;
        gap: 0.8rem;
    }
    .fileUploads div {
        background-color: var(--color-options-background-hover);
        border-radius: 0.5rem;
        padding: 0.4rem 0.8rem;
        font-size: 0.8rem;
        color: var(--color-text-primary);
        user-select: none;
        transition: background-color 0.3s, color 0.2s;
    }
    .fileUploads div i {
        width: 0.6rem;
        margin-right: 0.4rem;
        font-size: 0.8em;
    }
    .fileUploads div:hover {
        color: var(--color-dropzone-red);
        background-color: var(--color-input-background-focus);
        cursor: pointer;
    }
</style>
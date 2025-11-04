import pdfplumber
import docx


def extract_text_from_pdf(file):
    with pdfplumber.open(file) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])


def extract_text_from_txt(file):
    return file.read().decode('utf-8')


def extract_text_from_file(file):
    filename = file.filename.lower()
    if filename.endswith('.pdf'):
        return extract_text_from_pdf(file)
    elif filename.endswith('.docx'):
        return extract_text_from_docx(file)
    elif filename.endswith('.txt') or filename.endswith('.text') or filename.endswith('.md'):
        return extract_text_from_txt(file)
    else:
        raise ValueError("Unsupported file type. Only PDF, DOCX, TXT, and MD are supported.")
